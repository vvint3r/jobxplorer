#!/usr/bin/env python3
"""
Process Net New people rows from configured recruiter lists.

For each row: clicks Save, extracts recruiter fields (including email), writes CSV.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

script_dir = Path(__file__).resolve().parent


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower()
    return slug or "recruiter_list"


def _load_list_config(list_name: str) -> dict:
    config_path = script_dir / "apollo_recruiter_lists.json"
    with config_path.open(encoding="utf-8") as handle:
        lists = json.load(handle)
    if list_name not in lists:
        available = ", ".join(sorted(lists))
        raise SystemExit(
            f"Unknown list '{list_name}'. Available in apollo_recruiter_lists.json: {available}"
        )
    return lists[list_name]


def main() -> int:
    list_name = os.getenv("APOLLO_LIST_NAME", os.getenv("APOLLO_RECRUITER_LIST_NAME", "TechnicalRecruitersPublic"))
    cfg = _load_list_config(list_name)

    url = os.getenv("APOLLO_LIST_URL", cfg.get("url", "")).strip()
    if not url:
        raise SystemExit(
            f"No URL configured for '{list_name}'.\n"
            "Set APOLLO_LIST_URL or add the URL to apollo_recruiter_lists.json."
        )

    slug = _slugify(list_name)
    os.environ["APOLLO_LIST_URL"] = url
    os.environ.setdefault("FORCE_NET_NEW", "1")
    os.environ.setdefault("SKIP_EMAIL", "0")
    os.environ.setdefault("SKIP_PROSPECT", "0")
    os.environ.setdefault(
        "OUTPUT_STEM",
        cfg.get("output_stem", f"apollo_recruiter_records_{slug}_net_new"),
    )
    if cfg.get("output_dir"):
        os.environ.setdefault("OUTPUT_DIR", cfg["output_dir"])
    os.environ.setdefault("LOG_FILE", f"apollo_list_{slug}_net_new.log")
    os.environ.setdefault("HTML_PREFIX", f"apollo_list_{slug}_net_new_page_")

    print(f"Recruiter list mode: {list_name}")
    print(f"URL: {url[:120]}...")
    print(f"Output stem: {os.environ['OUTPUT_STEM']}")
    print(f"Log file: {os.environ['LOG_FILE']}\n")

    import apollo_recruiters

    apollo_recruiters.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
