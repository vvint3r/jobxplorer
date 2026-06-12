#!/usr/bin/env python3
"""Report Apollo extraction progress and recommended START_PAGE for resume."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
HTML_DIR = SCRIPT_DIR / "apollo_html"

PAGE_COMPLETE_RE = re.compile(r"Page (\d+) complete")
START_PAGE_RE = re.compile(r"Starting (?:recruiter )?extraction from page (\d+)")
DETECTED_TOTAL_PAGES_RE = re.compile(
    r"Detected total rows: [\d,]+, page size: \d+, total pages: (\d+)"
)
PROGRESS_SCOPE_RE = re.compile(r"(\d+) - (\d+) of ([\d,]+)")
TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
NUMBERED_CSV_RE = re.compile(r"_(\d+)\.csv$")


@dataclass
class PipelineConfig:
    key: str
    label: str
    log_file: Path
    html_prefix: str
    output_dir: Path
    output_stem: str


@dataclass
class RunSession:
    started_at: Optional[str] = None
    start_page: Optional[int] = None
    last_completed_page: Optional[int] = None
    last_completed_at: Optional[str] = None
    last_progress_scope: Optional[str] = None
    detected_total_pages: Optional[int] = None


@dataclass
class PipelineProgress:
    config: PipelineConfig
    log_exists: bool = False
    overall_last_completed_page: Optional[int] = None
    overall_last_completed_at: Optional[str] = None
    overall_last_progress_scope: Optional[str] = None
    detected_total_pages: Optional[int] = None
    html_highest_page: Optional[int] = None
    latest_csv: Optional[Path] = None
    latest_csv_rows: Optional[int] = None
    latest_run: RunSession = field(default_factory=RunSession)
    warnings: list[str] = field(default_factory=list)


PIPELINES = {
    "companies": PipelineConfig(
        key="companies",
        label="Companies",
        log_file=SCRIPT_DIR / "apollo_companies.log",
        html_prefix="apollo_companies_page_",
        output_dir=SCRIPT_DIR / "companies",
        output_stem="apollo_records_companies",
    ),
    "recruiters": PipelineConfig(
        key="recruiters",
        label="Recruiters",
        log_file=SCRIPT_DIR / "apollo_recruiters.log",
        html_prefix="apollo_recruiters_page_",
        output_dir=SCRIPT_DIR / "apollo_recruiters",
        output_stem="apollo_recruiter_records",
    ),
}


def _parse_timestamp(line: str) -> Optional[str]:
    match = TIMESTAMP_RE.match(line)
    return match.group(1) if match else None


def _parse_log(config: PipelineConfig) -> PipelineProgress:
    progress = PipelineProgress(config=config, log_exists=config.log_file.is_file())
    if not progress.log_exists:
        progress.warnings.append(f"Log file not found: {config.log_file}")
        return progress

    current_run = RunSession()

    with config.log_file.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            timestamp = _parse_timestamp(line)

            start_match = START_PAGE_RE.search(line)
            if start_match:
                current_run = RunSession(
                    started_at=timestamp,
                    start_page=int(start_match.group(1)),
                )

            detected_match = DETECTED_TOTAL_PAGES_RE.search(line)
            if detected_match:
                total_pages = int(detected_match.group(1))
                current_run.detected_total_pages = total_pages
                progress.detected_total_pages = total_pages

            complete_match = PAGE_COMPLETE_RE.search(line)
            if complete_match:
                page_num = int(complete_match.group(1))
                scope_match = PROGRESS_SCOPE_RE.search(line)

                progress.overall_last_completed_page = page_num
                progress.overall_last_completed_at = timestamp
                if scope_match:
                    progress.overall_last_progress_scope = scope_match.group(0)
                    total_rows = int(scope_match.group(3).replace(",", ""))
                    end_row = int(scope_match.group(2))
                    page_size = end_row - int(scope_match.group(1)) + 1
                    if page_size > 0 and progress.detected_total_pages is None:
                        progress.detected_total_pages = (total_rows + page_size - 1) // page_size

                current_run.last_completed_page = page_num
                current_run.last_completed_at = timestamp
                if scope_match:
                    current_run.last_progress_scope = scope_match.group(0)

    progress.latest_run = current_run
    if current_run.detected_total_pages:
        progress.detected_total_pages = current_run.detected_total_pages
    return progress


def _scan_html_highest_page(html_prefix: str) -> Optional[int]:
    """Return highest page number from the most recent dated HTML snapshot batch."""
    if not HTML_DIR.is_dir():
        return None

    page_re = re.compile(re.escape(html_prefix) + r"(\d+)_(\d{8})_")
    by_date: dict[str, list[int]] = {}
    for path in HTML_DIR.iterdir():
        if not path.is_file():
            continue
        match = page_re.search(path.name)
        if match:
            page_num = int(match.group(1))
            date_str = match.group(2)
            by_date.setdefault(date_str, []).append(page_num)

    if not by_date:
        return None

    latest_date = max(by_date)
    return max(by_date[latest_date])


def _latest_numbered_csv(output_dir: Path, output_stem: str) -> tuple[Optional[Path], Optional[int]]:
    if not output_dir.is_dir():
        return None, None

    best_run = -1
    best_path: Optional[Path] = None
    for path in output_dir.glob(f"{output_stem}_*.csv"):
        match = NUMBERED_CSV_RE.search(path.name)
        if not match:
            continue
        run_num = int(match.group(1))
        if run_num > best_run:
            best_run = run_num
            best_path = path

    if best_path is None:
        legacy = output_dir / f"{output_stem}.csv"
        if legacy.is_file():
            best_path = legacy
        else:
            return None, None

    with best_path.open(encoding="utf-8", errors="replace") as handle:
        row_count = max(0, sum(1 for _ in handle) - 1)
    return best_path, row_count


def analyze_pipeline(config: PipelineConfig) -> PipelineProgress:
    progress = _parse_log(config)
    progress.html_highest_page = _scan_html_highest_page(config.html_prefix)
    progress.latest_csv, progress.latest_csv_rows = _latest_numbered_csv(
        config.output_dir, config.output_stem
    )

    if progress.overall_last_completed_page is None and progress.html_highest_page is not None:
        progress.warnings.append(
            "No 'Page X complete' entries in log; falling back to highest HTML snapshot page."
        )
    elif (
        progress.overall_last_completed_page is not None
        and progress.html_highest_page is not None
        and progress.html_highest_page != progress.overall_last_completed_page
    ):
        progress.warnings.append(
            "Log and HTML page counts differ; prefer log value for resume."
        )

    return progress


def _recommended_start_page(progress: PipelineProgress) -> Optional[int]:
    last_page = progress.overall_last_completed_page
    if last_page is None:
        last_page = progress.html_highest_page
    if last_page is None:
        return 1
    return last_page + 1


def _is_complete(progress: PipelineProgress, start_page: int) -> bool:
    total_pages = progress.detected_total_pages
    if total_pages is None:
        return False
    last_page = progress.overall_last_completed_page or progress.html_highest_page
    if last_page is None:
        return False
    return last_page >= total_pages and start_page > total_pages


def format_report(progress: PipelineProgress) -> str:
    config = progress.config
    lines = [f"=== {config.label} ({config.key}) ==="]

    if not progress.log_exists and progress.html_highest_page is None:
        lines.append("No progress data found.")
        return "\n".join(lines)

    last_completed = progress.overall_last_completed_page
    if last_completed is None:
        last_completed = progress.html_highest_page
        last_source = "html snapshot"
    else:
        last_source = "log"

    start_page = _recommended_start_page(progress)

    lines.append(f"Log file:           {config.log_file}")
    lines.append(f"Last completed page ({last_source}): {last_completed if last_completed is not None else 'unknown'}")
    if progress.overall_last_completed_at:
        lines.append(f"Last completion at: {progress.overall_last_completed_at}")
    if progress.overall_last_progress_scope:
        lines.append(f"Last progress scope: {progress.overall_last_progress_scope}")
    if progress.detected_total_pages is not None:
        lines.append(f"Detected total pages: {progress.detected_total_pages}")
    if progress.html_highest_page is not None:
        lines.append(f"Highest HTML snapshot page: {progress.html_highest_page}")

    if progress.latest_run.start_page is not None:
        lines.append(
            f"Latest run:         started page {progress.latest_run.start_page}"
            + (f" at {progress.latest_run.started_at}" if progress.latest_run.started_at else "")
        )
        if progress.latest_run.last_completed_page is not None:
            lines.append(
                f"                    completed through page {progress.latest_run.last_completed_page}"
            )

    if progress.latest_csv:
        lines.append(f"Latest CSV:         {progress.latest_csv.name} ({progress.latest_csv_rows} data rows)")

    lines.append("")
    if last_completed is None:
        lines.append("Recommended START_PAGE: 1")
        lines.append("Status: No completed pages found yet.")
    elif _is_complete(progress, start_page):
        lines.append(f"Recommended START_PAGE: {start_page}")
        lines.append(
            f"Status: Extraction appears complete through page {last_completed} "
            f"of {progress.detected_total_pages}."
        )
    else:
        lines.append(f"Recommended START_PAGE: {start_page}")
        if progress.detected_total_pages:
            remaining = max(0, progress.detected_total_pages - last_completed)
            lines.append(f"Status: Resume needed — {remaining} page(s) remaining.")
        else:
            lines.append("Status: Resume from the next page after the last completed page.")

    if progress.warnings:
        lines.append("")
        for warning in progress.warnings:
            lines.append(f"Note: {warning}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show Apollo extraction progress and recommended START_PAGE."
    )
    parser.add_argument(
        "--pipeline",
        choices=["companies", "recruiters", "all"],
        default="all",
        help="Which pipeline to inspect (default: all)",
    )
    args = parser.parse_args()

    keys = list(PIPELINES.keys()) if args.pipeline == "all" else [args.pipeline]
    reports = [format_report(analyze_pipeline(PIPELINES[key])) for key in keys]
    print("\n\n".join(reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
