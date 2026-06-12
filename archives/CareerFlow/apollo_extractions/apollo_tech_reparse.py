#!/usr/bin/env python3
"""Dedupe all tech-orchestrator HTML snapshots into a single CSV.

Reuses the row-extraction logic from reparse_majorcompanies_html.py but globs
the orchestrator's ``apollo_tech_*_page_*.html`` files and dedupes primarily by
LinkedIn URL (companies are partitioned by employee range + asc/desc, so the
same company can appear in overlapping passes).
"""

import argparse
import re
from pathlib import Path

from reparse_majorcompanies_html import (
    COLUMNS,
    extract_row,
    parse_html_files,
    write_csv,
)

SCRIPT_DIR = Path(__file__).resolve().parent
HTML_DIR = SCRIPT_DIR / "apollo_html"
HTML_GLOB = "apollo_tech_*_page_*.html"
DEFAULT_OUTPUT = SCRIPT_DIR / "companies" / "lists" / "TechCompanies" / "apollo_records_techcompanies_1.csv"


def _row_score(row):
    return sum(1 for key in COLUMNS if row.get(key, "N/A") not in ("", "N/A"))


def _dedupe_linkedin_first(rows):
    best = {}
    order = []
    for row in rows:
        link = (row.get("LinkedIn URL") or "").strip().lower()
        name = re.sub(r"\s+", " ", (row.get("Company") or "").strip().lower())
        key = link if link and link != "n/a" else (name or None)
        if not key or key == "n/a":
            continue
        if key not in best:
            best[key] = row
            order.append(key)
        elif _row_score(row) > _row_score(best[key]):
            best[key] = row
    return [best[k] for k in order]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-dir", type=Path, default=HTML_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--glob", default=HTML_GLOB)
    args = parser.parse_args()

    rows = parse_html_files(args.html_dir, args.glob)
    deduped = _dedupe_linkedin_first(rows)
    write_csv(args.output, deduped)

    filled = {c: sum(1 for r in deduped if r.get(c, "N/A") not in ("", "N/A")) for c in COLUMNS}
    print(f"Parsed {len(rows)} raw rows -> {len(deduped)} unique companies")
    print(f"Output: {args.output}")
    for c in COLUMNS:
        print(f"  {c}: {filled[c]}/{len(deduped)} populated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
