#!/usr/bin/env python3
"""Crash-resilient supervisor for the target-orgs recruiter run.

The recruiter extractor (API prospect mode) has been crashing mid-run on
browser tab crashes. This wrapper restarts it from the last saved page until
the list is exhausted or no further progress is made. Resumes by appending to
the existing CSV; duplicates are removed later by LinkedIn URL.
"""

import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
HTML_DIR = SCRIPT_DIR / "apollo_html"
RUN_LOG = SCRIPT_DIR / "recruiter_supervisor_runs.log"
LOG = SCRIPT_DIR / "recruiter_supervisor.log"

LIST_NAME = os.getenv("APOLLO_LIST_NAME", "TechnicalRecruitersTargetOrgs")
HTML_PREFIX = "apollo_list_technicalrecruiterstargetorgs_net_new_page_"
OUTPUT_CSV = "apollo_recruiters/lists/TechnicalRecruitersTargetOrgs/apollo_recruiter_records_technical_target_orgs_net_new_1.csv"
# Net New compacts as contacts are prospected (they leave the list), so the
# next unprospected batch always sits at page 1. Always restart from page 1.
START_FLOOR = int(os.getenv("START_PAGE", "1"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "60"))
PER_ATTEMPT_TIMEOUT = int(os.getenv("PER_ATTEMPT_TIMEOUT", "5400"))
MAX_RUN_HOURS = float(os.getenv("MAX_RUN_HOURS", "8"))


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} - {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as h:
        h.write(line + "\n")


def max_saved_page():
    mx = 0
    pat = re.compile(re.escape(HTML_PREFIX) + r"(\d+)_")
    for f in HTML_DIR.glob(HTML_PREFIX + "*.html"):
        m = pat.search(f.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def csv_rows():
    """Row count of the output CSV (progress signal; grows as emails append,
    even within a single page that keeps crashing)."""
    path = SCRIPT_DIR / OUTPUT_CSV
    if not path.exists():
        return 0
    try:
        with path.open(encoding="utf-8", errors="ignore") as h:
            return sum(1 for _ in h)
    except Exception:
        return 0


def main():
    deadline = datetime.now() + timedelta(hours=MAX_RUN_HOURS)
    log("=" * 60)
    log(f"Recruiter supervisor start. list={LIST_NAME} page-1 drain mode "
        f"deadline={deadline:%H:%M}")

    prev_rows = -1
    stalls = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if datetime.now() >= deadline:
            log("Deadline reached; stopping.")
            break
        rows = csv_rows()
        start_page = START_FLOOR  # always page 1: Net New compacts as we prospect
        # Progress = CSV growth (emails appended). When Net New is drained, page 1
        # is empty and runs add nothing -> stop after several stalls.
        if rows == prev_rows:
            stalls += 1
            if stalls >= 4:
                log(f"No CSV growth ({rows} rows) across {stalls} attempts; Net New drained. Stopping.")
                break
        else:
            stalls = 0
        prev_rows = rows

        log(f"Attempt {attempt}: START_PAGE={start_page} (csv_rows={rows})")
        env = {
            **os.environ,
            "PROSPECT_MODE": "api",
            "PROSPECT_FALLBACK": "profile",
            "HEADLESS": "1",
            "APOLLO_LIST_NAME": LIST_NAME,
            "RESUME_OUTPUT_FILE": OUTPUT_CSV,
            "START_PAGE": str(start_page),
            # Process only the current page-1 batch per pass; Net New compacts
            # so the next batch is page 1 again on the following pass.
            "END_PAGE": "1",
        }
        try:
            with open(RUN_LOG, "a", encoding="utf-8") as rl:
                rl.write(f"\n===== attempt {attempt} START_PAGE={start_page} @ {datetime.now()} =====\n")
                rl.flush()
                subprocess.run(
                    [sys.executable, "apollo_list_net_new_recruiters.py"],
                    cwd=str(SCRIPT_DIR),
                    env=env,
                    stdout=rl,
                    stderr=subprocess.STDOUT,
                    timeout=PER_ATTEMPT_TIMEOUT,
                )
        except subprocess.TimeoutExpired:
            log(f"Attempt {attempt} timed out.")
        except Exception as exc:
            log(f"Attempt {attempt} error: {exc}")
        time.sleep(8)

    log(f"Supervisor finished at page {max_saved_page()}.")


if __name__ == "__main__":
    main()
