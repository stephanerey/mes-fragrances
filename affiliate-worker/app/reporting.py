from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def write_report(data_dir: Path, prefix: str, report: dict[str, object]) -> Path:
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = reports_dir / f"{prefix}_{timestamp}.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report_path


def write_named_report(data_dir: Path, filename: str, report: dict[str, object]) -> Path:
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path = reports_dir / filename
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report_path


def copy_report_to_latest(report_path: Path, latest_path: Path) -> Path:
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report_path, latest_path)
    return latest_path


def try_write_report(
    data_dir: Path,
    prefix: str,
    report: dict[str, object],
) -> Path | None:
    try:
        return write_report(data_dir, prefix, report)
    except OSError:
        return None


def try_write_named_report(
    data_dir: Path,
    filename: str,
    report: dict[str, object],
) -> Path | None:
    try:
        return write_named_report(data_dir, filename, report)
    except OSError:
        return None
