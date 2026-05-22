from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.awin import AwinCommandError, AwinService, format_report_summary
from app.config import get_settings
from app.logging_config import configure_logging
from app.preprocessing import FeedPreprocessor, format_preprocess_report_summary


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

    import_local_csv = subparsers.add_parser(
        "import-local-csv",
        help="Placeholder local CSV import command for PR01.",
    )
    import_local_csv.add_argument("--advertiser", required=True, type=int)
    import_local_csv.add_argument("--feed-id", required=True, type=int)
    import_local_csv.add_argument("--path", required=True, type=Path)
    import_local_csv.add_argument("--dry-run", action="store_true")

    import_feeds = subparsers.add_parser(
        "import-feeds",
        help="Placeholder remote feed import command for later PRs.",
    )
    import_feeds.add_argument("--network", required=True, choices=["awin"])
    import_feeds.add_argument("--download-only", action="store_true")
    import_feeds.add_argument("--dry-run", action="store_true")

    return parser


def run_show_config() -> int:
    settings = get_settings()
    print(json.dumps(settings.safe_dict(), indent=2, sort_keys=True))
    return 0


def run_import_local_csv(args: argparse.Namespace) -> int:
    print(
        "PR01 placeholder only: import-local-csv parsed successfully for "
        f"advertiser={args.advertiser}, feed_id={args.feed_id}, path={args.path}, "
        f"dry_run={args.dry_run}. No CSV parsing, Awin access, or database write was performed."
    )
    return 0


def run_import_feeds(args: argparse.Namespace) -> int:
    print(
        "Placeholder only: import-feeds parsed successfully for "
        f"network={args.network}, download_only={args.download_only}, dry_run={args.dry_run}. "
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
        if args.command == "import-local-csv":
            return run_import_local_csv(args)
        if args.command == "import-feeds":
            return run_import_feeds(args)
    except AwinCommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
