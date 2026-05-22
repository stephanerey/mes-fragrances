from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.awin import AwinCommandError, AwinService, format_report_summary
from app.config import get_settings
from app.db import (
    DatabaseService,
    DbCommandError,
    format_inspect_db_summary,
    format_migrate_db_summary,
)
from app.logging_config import configure_logging
from app.preprocessing import FeedPreprocessor, format_preprocess_report_summary
from app.raw_staging import (
    RawStagingError,
    RawStagingService,
    format_raw_staging_report_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main",
        description="Mes Fragrances affiliate worker CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "show-config",
        help="Display non-secret worker configuration.",
    )

    awin_list_feeds = subparsers.add_parser(
        "awin-list-feeds",
        help="Discover accessible Awin feeds and locate the target feed.",
    )
    awin_list_feeds.add_argument("--advertiser", default="105475")
    awin_list_feeds.add_argument("--feed-id", default="97867")
    awin_list_feeds.add_argument("--dry-run", action="store_true")

    awin_download_feed = subparsers.add_parser(
        "awin-download-feed",
        help="Download and inspect the target Awin feed header without DB writes.",
    )
    awin_download_feed.add_argument("--advertiser", required=True)
    awin_download_feed.add_argument("--feed-id", required=True)
    awin_download_feed.add_argument("--dry-run", action="store_true")

    preprocess_feed = subparsers.add_parser(
        "preprocess-feed",
        help="Parse the full feed and write a non-mutating preprocessing quality report.",
    )
    preprocess_feed.add_argument("--advertiser", required=True)
    preprocess_feed.add_argument("--feed-id", required=True)
    preprocess_feed.add_argument("--path", type=Path)

    subparsers.add_parser(
        "inspect-db",
        help="Inspect the connected database schema and existing catalog tables.",
    )

    migrate_db = subparsers.add_parser(
        "migrate-db",
        help="Plan or apply affiliate-worker SQL migrations.",
    )
    migrate_db.add_argument("--dry-run", action="store_true")
    migrate_db.add_argument("--plan", action="store_true")

    import_local_csv = subparsers.add_parser(
        "import-local-csv",
        help="Import a local CSV or gzip CSV feed into raw staging tables.",
    )
    import_local_csv.add_argument("--advertiser", required=True)
    import_local_csv.add_argument("--feed-id", required=True)
    import_local_csv.add_argument("--path", required=True, type=Path)
    import_local_csv.add_argument("--dry-run", action="store_true")

    import_feeds = subparsers.add_parser(
        "import-feeds",
        help="Import a remote feed or run a placeholder remote command for later PRs.",
    )
    import_feeds.add_argument("--network", required=True, choices=["awin"])
    import_feeds.add_argument("--advertiser")
    import_feeds.add_argument("--feed-id")
    import_feeds.add_argument("--raw-stage-only", action="store_true")
    import_feeds.add_argument("--download-only", action="store_true")
    import_feeds.add_argument("--dry-run", action="store_true")

    return parser


def run_show_config() -> int:
    settings = get_settings()
    print(json.dumps(settings.safe_dict(), indent=2, sort_keys=True))
    return 0


def run_import_local_csv(args: argparse.Namespace) -> int:
    settings = get_settings()
    report, report_path = RawStagingService(settings).import_local_csv(
        advertiser_id=str(args.advertiser),
        feed_id=str(args.feed_id),
        path=args.path,
        dry_run=args.dry_run,
    )
    print(format_raw_staging_report_summary(report, report_path))
    return 0


def run_import_feeds(args: argparse.Namespace) -> int:
    if args.raw_stage_only:
        if not args.advertiser or not args.feed_id:
            raise RawStagingError(
                "--advertiser and --feed-id are required with --raw-stage-only"
            )
        settings = get_settings()
        report, report_path = RawStagingService(settings).import_remote_feed(
            network=args.network,
            advertiser_id=str(args.advertiser),
            feed_id=str(args.feed_id),
            dry_run=args.dry_run,
        )
        print(format_raw_staging_report_summary(report, report_path))
        return 0

    print(
        "Placeholder only: import-feeds parsed successfully for "
        f"network={args.network}, raw_stage_only={args.raw_stage_only}, "
        f"download_only={args.download_only}, dry_run={args.dry_run}. "
        "No Awin request or database write was performed."
    )
    return 0


def run_awin_list_feeds(args: argparse.Namespace) -> int:
    settings = get_settings()
    report, report_path = AwinService(settings).list_feeds(
        advertiser_id=str(args.advertiser),
        feed_id=str(args.feed_id),
        dry_run=args.dry_run,
    )
    print(format_report_summary(report, report_path))
    return 0


def run_awin_download_feed(args: argparse.Namespace) -> int:
    settings = get_settings()
    report, report_path = AwinService(settings).download_feed(
        advertiser_id=str(args.advertiser),
        feed_id=str(args.feed_id),
        dry_run=args.dry_run,
    )
    print(format_report_summary(report, report_path))
    return 0


def run_preprocess_feed(args: argparse.Namespace) -> int:
    settings = get_settings()
    report, report_path = FeedPreprocessor(settings).preprocess_feed(
        advertiser_id=str(args.advertiser),
        feed_id=str(args.feed_id),
        path=args.path,
    )
    print(format_preprocess_report_summary(report, report_path))
    return 0


def run_inspect_db() -> int:
    settings = get_settings()
    report, report_path = DatabaseService(settings).inspect_db()
    print(format_inspect_db_summary(report, report_path))
    return 0


def run_migrate_db(args: argparse.Namespace) -> int:
    settings = get_settings()
    report, report_path = DatabaseService(settings).migrate_db(
        dry_run=args.dry_run,
        plan_only=args.plan,
    )
    print(format_migrate_db_summary(report, report_path))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.affiliate_log_level)

    try:
        if args.command == "show-config":
            return run_show_config()
        if args.command == "awin-list-feeds":
            return run_awin_list_feeds(args)
        if args.command == "awin-download-feed":
            return run_awin_download_feed(args)
        if args.command == "preprocess-feed":
            return run_preprocess_feed(args)
        if args.command == "inspect-db":
            return run_inspect_db()
        if args.command == "migrate-db":
            return run_migrate_db(args)
        if args.command == "import-local-csv":
            return run_import_local_csv(args)
        if args.command == "import-feeds":
            return run_import_feeds(args)
    except (AwinCommandError, DbCommandError, RawStagingError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
