#!/usr/bin/env python3
"""Overnight tech-company extractor that defeats Apollo's 100-page (2,500 row)
display cap by recursively partitioning the search space.

Strategy
--------
Apollo only lets you page through the first 2,500 results of any search. We
work around this WITHOUT creating saved lists by rotating filter parameters:

  * Primary partition: ``organizationNumEmployeesRanges`` (custom min,max ranges
    are honored by Apollo, verified live).
  * Secondary trick: ``sortAscending`` desc+asc doubles reachable rows to 5,000
    for a given segment (top 2,500 + bottom 2,500).

For each candidate employee range we read the live result count and:
  * total <= 2,500  -> one ``desc`` pass (<=100 pages)
  * total <= 5,000  -> ``desc`` pass + ``asc`` pass (covers the whole range)
  * total >  5,000  -> bisect the employee range and recurse

Each leaf pass is run by the existing ``apollo_companies.py`` extractor in
COLLECT_HTML_ONLY mode (saves page HTML only -- no Save clicks, no credits) and
is auto-restarted from the last saved page if the browser crashes. State is
tracked in JSON so the whole run is resumable. Run ``apollo_tech_reparse.py``
afterwards to dedupe all saved HTML into a single CSV.
"""

import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
JOBX_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(JOBX_ROOT / "src" / "job_extraction"))

from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402

from apollo_companies import (  # noqa: E402
    setup_virtual_display,
    load_cookies,
    parse_progress_stats,
)
from driver_utils import create_driver, cleanup_driver  # noqa: E402

PAGINATION_XPATH = "//*[@data-interaction-boundary='Table Pagination']"
PROGRESS_RE = re.compile(r"\d[\d,]*\s*-\s*\d[\d,]*\s+of\s+[\d,]+")


def read_scoped_progress(driver):
    """Read the pagination 'X - Y of Z' counter ONLY from the Table Pagination
    widget (avoids stray 'of N' text elsewhere on the page)."""
    for el in driver.find_elements(By.XPATH, PAGINATION_XPATH + "//*[contains(normalize-space(.), ' of ')]"):
        text = " ".join((el.text or el.get_attribute("textContent") or "").split())
        m = PROGRESS_RE.search(text)
        if m:
            return m.group(0)
    return None

HTML_DIR = SCRIPT_DIR / "apollo_html"
STATE_FILE = SCRIPT_DIR / "tech_orchestrator_state.json"
LOG_FILE = SCRIPT_DIR / "tech_orchestrator.log"
RUN_LOG = SCRIPT_DIR / "tech_orchestrator_runs.log"

PAGE_SIZE = 25
PAGE_CAP = 100
SINGLE_CAP = PAGE_CAP * PAGE_SIZE  # 2500
DOUBLE_CAP = SINGLE_CAP * 2        # 5000

# Tech = Computer Software + Information Technology & Services + Internet.
TECH = (
    "&organizationIndustryTagIds[]=5567cd4773696439b10b0000"
    "&organizationIndustryTagIds[]=5567cd4e7369643b70010000"
    "&organizationIndustryTagIds[]=5567cd4d7369644d39040000"
)
US = "&organizationLocations[]=United%20States"

# Standard Apollo employee boundaries we seed the planner with (>= EMP_FLOOR).
SEED_BUCKETS = [
    (51, 100), (101, 200), (201, 500), (501, 1000),
    (1001, 2000), (2001, 5000), (5001, 10000), (10001, None),
]

EMP_FLOOR = int(os.getenv("EMP_FLOOR", "51"))
MAX_RUN_HOURS = float(os.getenv("MAX_RUN_HOURS", "11"))
MAX_LEAF_RETRIES = int(os.getenv("MAX_LEAF_RETRIES", "6"))
PER_LEAF_TIMEOUT = int(os.getenv("PER_LEAF_TIMEOUT", "5400"))  # 90 min/leaf hard cap
COUNT_WAIT = float(os.getenv("COUNT_WAIT", "7"))


def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def emp_param(lo, hi):
    if hi is None:
        return f"&organizationNumEmployeesRanges[]={lo}"
    return f"&organizationNumEmployeesRanges[]={lo}%2C{hi}"


def seg_url(lo, hi, asc):
    sort = "true" if asc else "false"
    return (
        "https://app.apollo.io/#/companies?sortByField=%5Bnone%5D&page=1"
        f"&sortAscending={sort}" + US + TECH + emp_param(lo, hi)
    )


def leaf_key(lo, hi, sort):
    return f"{lo}_{hi if hi is not None else 'plus'}_{sort}"


def html_prefix(lo, hi, sort):
    return f"apollo_tech_{leaf_key(lo, hi, sort)}_page_"


def max_saved_page(prefix):
    mx = 0
    pat = re.compile(re.escape(prefix) + r"(\d+)_")
    for f in HTML_DIR.glob(prefix + "*.html"):
        m = pat.search(f.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def get_total(driver, lo, hi):
    """Return the live result count for an employee range, reading only the
    pagination-scoped counter once the table has rendered. Requires two
    consecutive agreeing reads to guard against transient misreads."""
    for attempt in range(3):
        try:
            driver.get(seg_url(lo, hi, asc=False))
            # Wait for the pagination widget AND a table row to render.
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.XPATH, PAGINATION_XPATH))
                )
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.XPATH, "//div[contains(@id, 'table-row-')]"))
                )
            except Exception:
                pass
            time.sleep(COUNT_WAIT)

            reads = []
            for _ in range(2):
                text = read_scoped_progress(driver)
                stats = parse_progress_stats(text) if text else None
                reads.append(stats["total_rows"] if stats else None)
                time.sleep(2)
            if reads[0] is not None and reads[0] == reads[1]:
                return reads[0]
            # Disagreement or missing -> one more settle + read.
            time.sleep(3)
            text = read_scoped_progress(driver)
            stats = parse_progress_stats(text) if text else None
            if stats:
                return stats["total_rows"]
        except Exception as exc:
            log(f"  count error ({lo},{hi}) attempt {attempt+1}: {exc}")
        time.sleep(3)
    return None


def expected_pages(total, sort):
    if sort == "desc":
        return min(PAGE_CAP, max(1, math.ceil(total / PAGE_SIZE)))
    # asc only needs to cover the rows beyond the first 2,500.
    remainder = max(0, total - SINGLE_CAP)
    return min(PAGE_CAP, max(1, math.ceil(remainder / PAGE_SIZE)))


def plan_segment(driver, lo, hi, leaves):
    total = get_total(driver, lo, hi)
    label = f"{lo}-{hi if hi is not None else 'plus'}"
    if not total:
        log(f"  [{label}] count unavailable -> skipping")
        return
    log(f"  [{label}] total={total}")
    if total <= SINGLE_CAP:
        leaves.append({"lo": lo, "hi": hi, "total": total, "sort": "desc"})
    elif total <= DOUBLE_CAP:
        leaves.append({"lo": lo, "hi": hi, "total": total, "sort": "desc"})
        leaves.append({"lo": lo, "hi": hi, "total": total, "sort": "asc"})
    else:
        if hi is None or hi <= lo:
            # Cannot split a single-headcount segment; best effort (may miss middle).
            log(f"  [{label}] >5000 but unsplittable -> desc+asc best effort")
            leaves.append({"lo": lo, "hi": hi, "total": total, "sort": "desc"})
            leaves.append({"lo": lo, "hi": hi, "total": total, "sort": "asc"})
        else:
            mid = (lo + hi) // 2
            plan_segment(driver, lo, mid, leaves)
            plan_segment(driver, mid + 1, hi, leaves)


def build_plan():
    display = setup_virtual_display()
    driver = create_driver(profile_name="apollo_tech_plan", headless=True)
    leaves = []
    try:
        load_cookies(driver)
        for lo, hi in SEED_BUCKETS:
            if hi is not None and hi < EMP_FLOOR:
                continue
            start_lo = max(lo, EMP_FLOOR)
            plan_segment(driver, start_lo, hi, leaves)
    finally:
        cleanup_driver(driver)
        if display:
            display.stop()
    # Largest companies first (highest value), desc before asc within a range.
    leaves.sort(key=lambda d: (-d["lo"], 0 if d["sort"] == "desc" else 1))
    for leaf in leaves:
        leaf["expected"] = expected_pages(leaf["total"], leaf["sort"])
        leaf["key"] = leaf_key(leaf["lo"], leaf["hi"], leaf["sort"])
    return leaves


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run_leaf(leaf):
    lo, hi, sort = leaf["lo"], leaf["hi"], leaf["sort"]
    prefix = html_prefix(lo, hi, sort)
    expected = leaf["expected"]
    url = seg_url(lo, hi, asc=(sort == "asc"))

    prev_saved = -1
    stalls = 0
    for attempt in range(1, MAX_LEAF_RETRIES + 1):
        saved = max_saved_page(prefix)
        if saved >= expected:
            log(f"  {leaf['key']}: complete ({saved}/{expected} pages)")
            return True, saved
        # If a clean run added no new pages, the real end is below `expected`
        # (Apollo returned fewer rows than the planned count). Treat as done.
        if saved == prev_saved and saved > 0:
            stalls += 1
            if stalls >= 2:
                log(f"  {leaf['key']}: no further pages (real end {saved} < expected {expected}); done")
                return True, saved
        else:
            stalls = 0
        prev_saved = saved
        start_page = saved + 1
        log(f"  {leaf['key']}: attempt {attempt} START_PAGE={start_page} END_PAGE={expected}")
        env = {
            **os.environ,
            "APOLLO_LIST_URL": url,
            "COLLECT_HTML_ONLY": "1",
            "SKIP_SAVE": "1",
            "SKIP_NET_NEW": "1",
            "HEADLESS": "1",
            "HTML_PREFIX": prefix,
            "START_PAGE": str(start_page),
            "END_PAGE": str(expected),
            "BREAK_EVERY_MIN_PAGES": "8",
            "BREAK_EVERY_MAX_PAGES": "15",
            "BREAK_MIN_SECONDS": "10",
            "BREAK_MAX_SECONDS": "25",
        }
        try:
            with open(RUN_LOG, "a", encoding="utf-8") as rl:
                rl.write(f"\n===== {leaf['key']} attempt {attempt} @ {datetime.now()} =====\n")
                rl.flush()
                subprocess.run(
                    [sys.executable, "apollo_companies.py"],
                    cwd=str(SCRIPT_DIR),
                    env=env,
                    stdout=rl,
                    stderr=subprocess.STDOUT,
                    timeout=PER_LEAF_TIMEOUT,
                )
        except subprocess.TimeoutExpired:
            log(f"  {leaf['key']}: attempt {attempt} timed out after {PER_LEAF_TIMEOUT}s")
        except Exception as exc:
            log(f"  {leaf['key']}: attempt {attempt} error: {exc}")
        time.sleep(5)

    saved = max_saved_page(prefix)
    ok = saved >= expected
    log(f"  {leaf['key']}: {'done' if ok else 'PARTIAL'} ({saved}/{expected} pages)")
    return ok, saved


def main():
    deadline = datetime.now() + timedelta(hours=MAX_RUN_HOURS)
    log("=" * 70)
    log(f"Tech orchestrator start. EMP_FLOOR={EMP_FLOOR} deadline={deadline:%H:%M} "
        f"max_hours={MAX_RUN_HOURS}")

    state = load_state()
    if "plan" not in state:
        log("Building partition plan (reading live counts)...")
        leaves = build_plan()
        state = {
            "created": datetime.now().isoformat(),
            "plan": leaves,
            "leaves": {leaf["key"]: {"status": "pending", "expected": leaf["expected"],
                                     "total": leaf["total"]} for leaf in leaves},
        }
        save_state(state)
        total_pages = sum(leaf["expected"] for leaf in leaves)
        unique_ranges = {(leaf["lo"], leaf["hi"]): leaf["total"] for leaf in leaves}
        log(f"Plan: {len(leaves)} leaf passes, ~{total_pages} pages, "
            f"covering ~{sum(unique_ranges.values())} companies (pre-dedupe).")
    else:
        leaves = state["plan"]
        log(f"Resuming existing plan: {len(leaves)} leaf passes.")

    for leaf in leaves:
        key = leaf["key"]
        if state["leaves"].get(key, {}).get("status") == "done":
            continue
        if datetime.now() >= deadline:
            log(f"Deadline reached; stopping before {key}. Re-run to continue.")
            break
        log(f"Leaf {key} (emp {leaf['lo']}-{leaf['hi']}, {leaf['sort']}, "
            f"total={leaf['total']}, expect {leaf['expected']} pages)")
        ok, saved = run_leaf(leaf)
        state["leaves"][key] = {
            "status": "done" if ok else "partial",
            "expected": leaf["expected"],
            "pages_saved": saved,
            "total": leaf["total"],
            "updated": datetime.now().isoformat(),
        }
        save_state(state)

    done = sum(1 for v in state["leaves"].values() if v["status"] == "done")
    log(f"Orchestrator pass finished: {done}/{len(leaves)} leaves done.")
    log("Run: python3 apollo_tech_reparse.py  to build the deduped CSV.")


if __name__ == "__main__":
    main()
