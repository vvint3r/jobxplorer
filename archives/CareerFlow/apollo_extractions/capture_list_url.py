#!/usr/bin/env python3
"""Capture the Apollo browser URL for a saved list (Net New tab) into apollo_lists.json."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

script_dir = Path(__file__).resolve().parent
jobxplore_root = script_dir.parents[2]
sys.path.insert(0, str(jobxplore_root / "src" / "job_extraction"))

from apollo_companies import load_cookies, setup_virtual_display  # noqa: E402
from driver_utils import cleanup_driver, create_driver  # noqa: E402


def load_lists_config() -> dict:
    config_path = script_dir / "apollo_lists.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing config file: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_list_url(list_name: str, url: str) -> Path:
    config_path = script_dir / "apollo_lists.json"
    data = load_lists_config()
    if list_name not in data:
        raise KeyError(f"List '{list_name}' is not defined in {config_path}")
    data[list_name]["url"] = url.strip()
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    return config_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture Apollo list URL after you open the list on the Net New tab."
    )
    parser.add_argument(
        "--list",
        default="MajorCompanies",
        help="List name key in apollo_lists.json (default: MajorCompanies)",
    )
    args = parser.parse_args()

    lists = load_lists_config()
    if args.list not in lists:
        print(f"Unknown list '{args.list}'. Available: {', '.join(sorted(lists))}")
        return 1

    print(f"\nCapturing URL for list: {args.list}")
    print("1. Browser will open and log in via cookies.")
    print("2. Navigate to your saved list in Apollo.")
    print("3. Click the **Net New** tab (unsaved rows with '+ Save').")
    print("4. Return here and press Enter to save the current URL.\n")

    display = setup_virtual_display()
    driver = create_driver(profile_name="apollo_capture_list_url")
    try:
        load_cookies(driver)
        driver.get("https://app.apollo.io/#/companies")
        time.sleep(3)
        input("Press Enter when the Net New tab for your list is visible in the browser...")
        url = driver.current_url.strip()
        if "#/companies" not in url:
            print(f"Warning: URL does not look like a companies list page:\n{url}")
        config_path = save_list_url(args.list, url)
        print(f"\nSaved URL for '{args.list}' to {config_path}")
        print(f"URL: {url}")
        print(f"\nRun next:\n  APOLLO_LIST_NAME={args.list} python3 apollo_list_net_new.py")
    finally:
        cleanup_driver(driver)
        display.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
