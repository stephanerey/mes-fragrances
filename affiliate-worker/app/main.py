from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings, load_settings
from app.logging_config import configure_logging

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="affiliate-worker",
        description="Affiliate feed worker for mes-fragrances.com.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="mes-fragrances-affiliate-worker 0.1.0",
    )

    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser(
        "show-config",
        help="Show non-secret effective configuration.",
    )
    config_parser.set_defaults(handler=handle_show_config)

    import_local_parser = subparsers.add_parser(
        "import-local-csv",
        help="Validate a local CSV import command skeleton.",
    )
    import_local_parser.add_argument("--advertiser", required=True, help="Network advertiser id.")
    import_local_parser.add_argument("--feed-id", required=True, help="Network feed id.")
    import_local_parser.add_argument("--path", required=True, help="Path to the CSV feed file.")
    import_local_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs without mutating database state. DB writes are not implemented in PR1.",
    )
    import_local_parser.set_defaults(handler=handle_import_local_csv)

    import_feeds_parser = subparsers.add_parser(
        "import-feeds",
        help="Placeholder for future live feed imports.",
    )
    import_feeds_parser.add_argument("--network", default="awin", help="Affiliate network name.")
    import_feeds_parser.add_argument("--dry-run", action="store_true", help="Run without mutations.")
    import_feeds_parser.set_defaults(handler=handle_import_feeds)

    return parser


def handle_show_config(args: argparse.Namespace, settings: Settings) -> int:
    settings.ensure_data_dirs()
    payload = {
        "import_mode": settings.import_mode,
        "log_level": settings.log_level,
        "data_dir": str(settings.data_dir),
        "feeds_dir": str(settings.feeds_dir),
        "reports_dir": str(settings.reports_dir),
        "logs_dir": str(settings.logs_dir),
        "database_url_configured": settings.database_url is not None,
        "awin_publisher_id_configured": settings.awin_publisher_id is not None,
        "awin_api_token_configured": settings.awin_api_token is not None,
        "awin_product_feed_api_key_configured": settings.awin_product_feed_api_key is not None,
        "deactivate_after_missed_imports": settings.deactivate_after_missed_imports,
        "match_auto_threshold": settings.match_auto_threshold,
        "match_review_threshold": settings.match_review_threshold,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def handle_import_local_csv(args: argparse.Namespace, settings: Settings) -> int:
    settings.ensure_data_dirs()
    csv_path = Path(args.path)

    if not csv_path.exists():
        LOGGER.error("CSV file does not exist: %s", csv_path)
        return 2

    if not csv_path.is_file():
        LOGGER.error("CSV path is not a file: %s", csv_path)
        return 2

    report = {
        "status": "validated",
        "message": "PR1 skeleton only: CSV parsing and database writes are implemented in later PRs.",
        "advertiser_id": args.advertiser,
        "feed_id": args.feed_id,
        "path": str(csv_path),
        "dry_run": bool(args.dry_run),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    report_path = settings.reports_dir / "last_import_local_csv_skeleton.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    LOGGER.info(
        "Validated local CSV import skeleton for advertiser=%s feed_id=%s dry_run=%s report=%s",
        args.advertiser,
        args.feed_id,
        args.dry_run,
        report_path,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def handle_import_feeds(args: argparse.Namespace, settings: Settings) -> int:
    settings.ensure_data_dirs()
    LOGGER.warning("Live feed import is not implemented in PR1. network=%s dry_run=%s", args.network, args.dry_run)
    return 3


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    configure_logging(settings.log_level)

    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        return 0

    return args.handler(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
