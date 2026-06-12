#!/usr/bin/env python3
"""
Process Net New rows from a saved Apollo company list.

For each row: clicks Save (moves company into Saved) and extracts fields to CSV.
Designed for lists like MajorCompanies where Net New still has unsaved companies.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent


def _load_list_config(list_name: str) -> dict:
    config_path = script_dir / "apollo_lists.json"
    with config_path.open(encoding="utf-8") as handle:
        lists = json.load(handle)
    if list_name not in lists:
        available = ", ".join(sorted(lists))
        raise SystemExit(
            f"Unknown list '{list_name}'. Available in apollo_lists.json: {available}"
        )
    return lists[list_name]


def main() -> int:
    list_name = os.getenv("APOLLO_LIST_NAME", "MajorCompanies")
    cfg = _load_list_config(list_name)

    url = os.getenv("APOLLO_LIST_URL", cfg.get("url", "")).strip()
    if not url:
        raise SystemExit(
            f"No URL configured for '{list_name}'.\n"
            "Either:\n"
            f"  1) Run: python3 capture_list_url.py --list {list_name}\n"
            "  2) Or set APOLLO_LIST_URL to the browser URL while on the Net New tab."
        )

    os.environ["APOLLO_LIST_URL"] = url
    os.environ.setdefault("FORCE_NET_NEW", "1")
    os.environ.setdefault("OUTPUT_STEM", cfg.get("output_stem", f"apollo_records_{list_name.lower()}_net_new"))
    if cfg.get("output_dir"):
        os.environ.setdefault("OUTPUT_DIR", cfg["output_dir"])
    os.environ.setdefault("LOG_FILE", f"apollo_list_{list_name.lower()}_net_new.log")
    os.environ.setdefault("HTML_PREFIX", f"apollo_list_{list_name.lower()}_net_new_page_")

    print(f"List mode: {list_name}")
    print(f"URL: {url}")
    print(f"Output stem: {os.environ['OUTPUT_STEM']}")
    print(f"Log file: {os.environ['LOG_FILE']}\n")

    import apollo_companies

    apollo_companies.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
