from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.logging_config import configure_logging


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
        help="Placeholder remote feed import command for PR01.",
    )
    import_feeds.add_argument("--network", required=True, choices=["awin"])
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
        "PR01 placeholder only: import-feeds parsed successfully for "
        f"network={args.network}, dry_run={args.dry_run}. "
        "No Awin request or database write was performed."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.affiliate_log_level)

    if args.command == "show-config":
        return run_show_config()
    if args.command == "import-local-csv":
        return run_import_local_csv(args)
    if args.command == "import-feeds":
        return run_import_feeds(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
