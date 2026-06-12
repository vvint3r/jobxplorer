#!/usr/bin/env python3
"""Re-extract MajorCompanies Net New rows from saved Apollo HTML snapshots."""

from __future__ import annotations

import argparse
import csv
import re
from html import unescape
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
HTML_DIR = SCRIPT_DIR / "apollo_html"
HTML_GLOB = "apollo_list_majorcompanies_net_new_page_*.html"
DEFAULT_OUTPUT = (
    SCRIPT_DIR / "companies" / "lists" / "MajorCompanies" / "apollo_records_majorcompanies_net_new_1.csv"
)

COLUMNS = ["Company", "LinkedIn URL", "Location", "# Employees", "Industry", "Keywords"]


def _cell_html(row_html: str, colindex: str) -> str:
    match = re.search(
        rf'<div[^>]*role="gridcell"[^>]*aria-colindex="{colindex}"[^>]*>(.*?)'
        rf'(?=<div[^>]*role="gridcell"|<div[^>]*class="zp_Uiy0R")',
        row_html,
        re.DOTALL,
    )
    return match.group(1) if match else ""


def _cell_tags(cell_html: str) -> list[str]:
    tags = []
    for raw in re.findall(r'class="text-caption-medium zp_z4aAi"[^>]*>([^<]+)', cell_html):
        text = unescape(raw.strip())
        if text.startswith("+"):
            tags.append(text)
        elif text:
            tags.append(text)
    return tags


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.DOTALL)
    return unescape(match.group(1).strip()) if match else "N/A"


def extract_row(row_html: str) -> dict[str, str]:
    company_cell = _cell_html(row_html, "1")
    employees_cell = _cell_html(row_html, "4")
    industry_cell = _cell_html(row_html, "5")
    keywords_cell = _cell_html(row_html, "6")
    location_cell = _cell_html(row_html, "7")

    company = _first_match(r'zp_CaeaN[^>]*>([^<]+)', company_cell)
    if company == "N/A":
        company = _first_match(r'data-link-variant="default"[^>]*>.*?<span[^>]*>([^<]+)', company_cell)

    linkedin = "N/A"
    for href in re.findall(r'href="([^"]*linkedin\.com/company[^"]*)"', row_html):
        linkedin = href
        break
    if linkedin == "N/A":
        for href in re.findall(r'href="([^"]*linkedin[^"]*)"', row_html):
            linkedin = href
            break

    employees = _first_match(r'data-count-size="[^"]*"[^>]*>([^<]+)', employees_cell)
    location = _first_match(r'zp_FEm_X[^>]*>([^<]+)', location_cell)

    industry_tags = _cell_tags(industry_cell)
    keyword_tags = _cell_tags(keywords_cell)

    return {
        "Company": company,
        "LinkedIn URL": linkedin,
        "Location": location,
        "# Employees": employees,
        "Industry": "; ".join(industry_tags) if industry_tags else "N/A",
        "Keywords": "; ".join(keyword_tags) if keyword_tags else "N/A",
    }


def parse_html_files(html_dir: Path, glob_pattern: str) -> list[dict[str, str]]:
    files = sorted(html_dir.glob(glob_pattern), key=lambda p: p.name)
    if not files:
        raise SystemExit(f"No HTML files matching {glob_pattern} in {html_dir}")

    rows: list[dict[str, str]] = []
    for html_file in files:
        html = html_file.read_text(encoding="utf-8", errors="ignore")
        index = 0
        while True:
            start = html.find(f'id="table-row-{index}"')
            if start < 0:
                break
            end = html.find(f'id="table-row-{index + 1}"')
            row_html = html[start:end] if end > start else html[start:]
            rows.append(extract_row(row_html))
            index += 1
    return rows


def _norm_company(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _row_score(row: dict[str, str]) -> int:
    return sum(1 for key in COLUMNS if row.get(key, "N/A") not in ("", "N/A"))


def dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    best: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for row in rows:
        key = _norm_company(row.get("Company", ""))
        if not key or key == "n/a":
            key = row.get("LinkedIn URL", "").strip().lower() or f"row-{len(order)}"
        if key not in best:
            best[key] = row
            order.append(key)
            continue
        if _row_score(row) > _row_score(best[key]):
            best[key] = row
    return [best[key] for key in order]


def merge_rows(existing: list[dict[str, str]], reparsed: list[dict[str, str]]) -> list[dict[str, str]]:
    combined = existing + reparsed
    return dedupe_rows(combined)


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-dir", type=Path, default=HTML_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge with existing output CSV before deduping (default: replace from HTML only).",
    )
    args = parser.parse_args()

    reparsed = parse_html_files(args.html_dir, HTML_GLOB)
    if args.merge_existing:
        existing = load_csv(args.output)
        final_rows = merge_rows(existing, reparsed)
    else:
        final_rows = dedupe_rows(reparsed)

    write_csv(args.output, final_rows)

    filled = {col: sum(1 for r in final_rows if r.get(col, "N/A") not in ("", "N/A")) for col in COLUMNS}
    print(f"Wrote {len(final_rows)} deduped rows to {args.output}")
    for col in COLUMNS:
        print(f"  {col}: {filled[col]}/{len(final_rows)} populated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
