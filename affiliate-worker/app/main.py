from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.awin import AwinCommandError, AwinService, format_report_summary
from app.candidates import (
    CandidateError,
    CandidateService,
    format_candidate_report_summary,
    format_insert_candidate_sync_summary,
)
from app.config import get_settings
from app.db import (
    DatabaseService,
    DbCommandError,
    format_inspect_db_summary,
    format_migrate_db_summary,
)
from app.logging_config import configure_logging
from app.matching import (
    MatchingError,
    MatchingService,
    format_matching_report_summary,
)
from app.normalization import (
    NormalizationError,
    NormalizationService,
    format_normalization_report_summary,
)
from app.pipeline import PipelineService, format_pipeline_report_summary
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

    normalize_feed = subparsers.add_parser(
        "normalize-feed",
        help="Normalize raw staged feed rows and report actionable fragrance rows.",
    )
    normalize_feed.add_argument("--advertiser", required=True)
    normalize_feed.add_argument("--feed-id", required=True)
    normalize_feed.add_argument("--dry-run", action="store_true")
    normalize_feed.add_argument("--import-run-id", type=int)
    normalize_feed.add_argument("--limit", type=int)

    match_offers = subparsers.add_parser(
        "match-offers",
        help="Match normalized fragrance rows to the CIS catalog and upsert affiliate offers.",
    )
    match_offers.add_argument("--advertiser", required=True)
    match_offers.add_argument("--feed-id", required=True)
    match_offers.add_argument("--dry-run", action="store_true")
    match_offers.add_argument("--limit", type=int)
    match_offers.add_argument("--min-score", type=int)
    match_offers.add_argument("--disable-fuzzy", action="store_true")
    match_offers.add_argument("--no-stale-update", action="store_true")

    create_candidates = subparsers.add_parser(
        "create-candidates",
        help="Create or update reviewable product candidates from normalized feed rows.",
    )
    create_candidates.add_argument("--advertiser", required=True)
    create_candidates.add_argument("--feed-id", required=True)
    create_candidates.add_argument("--dry-run", action="store_true")
    create_candidates.add_argument("--limit", type=int)
    create_candidates.add_argument("--include-excluded", action="store_true")
    create_candidates.add_argument("--disable-fuzzy", action="store_true")
    create_candidates.add_argument("--min-review-score", type=int)

    sync_insert_candidates = subparsers.add_parser(
        "sync-perfume-insert-candidates",
        help=(
            "Synchronize open product_match_candidates into "
            "public.perfume_insert_candidates without promoting perfumes."
        ),
    )
    sync_insert_candidates.add_argument("--advertiser", required=True)
    sync_insert_candidates.add_argument("--feed-id", required=True)
    sync_insert_candidates.add_argument("--dry-run", action="store_true")
    sync_insert_candidates.add_argument("--limit", type=int)
    sync_insert_candidates.add_argument("--report-dir", type=Path)
    sync_insert_candidates.add_argument("--only-status", default="pending,needs_review")

    run_pipeline = subparsers.add_parser(
        "run-affiliate-pipeline",
        help="Run the full affiliate pipeline for active feeds with aggregate reporting.",
    )
    run_pipeline.add_argument("--network", required=True, choices=["awin"])
    run_pipeline.add_argument("--advertiser")
    run_pipeline.add_argument("--feed-id")
    run_pipeline.add_argument("--dry-run", action="store_true")
    run_pipeline.add_argument("--random-delay-max-seconds", type=int, default=0)
    run_pipeline.add_argument("--skip-candidates", action="store_true")
    run_pipeline.add_argument("--no-stale-update", action="store_true")

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


def run_normalize_feed(args: argparse.Namespace) -> int:
    settings = get_settings()
    report, report_path = NormalizationService(settings).normalize_feed(
        advertiser_id=str(args.advertiser),
        feed_id=str(args.feed_id),
        dry_run=args.dry_run,
        import_run_id=args.import_run_id,
        limit=args.limit,
    )
    print(format_normalization_report_summary(report, report_path))
    return 0


def run_match_offers(args: argparse.Namespace) -> int:
    settings = get_settings()
    report, report_path = MatchingService(settings).match_offers(
        advertiser_id=str(args.advertiser),
        feed_id=str(args.feed_id),
        dry_run=args.dry_run,
        limit=args.limit,
        min_score=args.min_score,
        disable_fuzzy=args.disable_fuzzy,
        no_stale_update=args.no_stale_update,
    )
    print(format_matching_report_summary(report, report_path))
    return 0


def run_create_candidates(args: argparse.Namespace) -> int:
    settings = get_settings()
    report, report_path = CandidateService(settings).create_candidates(
        advertiser_id=str(args.advertiser),
        feed_id=str(args.feed_id),
        dry_run=args.dry_run,
        limit=args.limit,
        include_excluded=args.include_excluded,
        disable_fuzzy=args.disable_fuzzy,
        min_review_score=args.min_review_score,
    )
    print(format_candidate_report_summary(report, report_path))
    return 0


def run_sync_perfume_insert_candidates(args: argparse.Namespace) -> int:
    settings = get_settings()
    only_statuses = [
        status.strip() for status in str(args.only_status).split(",") if status.strip()
    ]
    if not only_statuses:
        raise CandidateError("--only-status must contain at least one status")
    report, report_path = CandidateService(settings).sync_perfume_insert_candidates(
        advertiser_id=str(args.advertiser),
        feed_id=str(args.feed_id),
        dry_run=args.dry_run,
        limit=args.limit,
        report_dir=args.report_dir,
        only_statuses=only_statuses,
    )
    print(format_insert_candidate_sync_summary(report, report_path))
    return 0


def run_affiliate_pipeline(args: argparse.Namespace) -> int:
    settings = get_settings()
    result = PipelineService(settings).run_pipeline(
        network=args.network,
        dry_run=args.dry_run,
        advertiser_id=str(args.advertiser) if args.advertiser is not None else None,
        feed_id=str(args.feed_id) if args.feed_id is not None else None,
        random_delay_max_seconds=args.random_delay_max_seconds,
        skip_candidates=args.skip_candidates,
        no_stale_update=args.no_stale_update,
    )
    output = format_pipeline_report_summary(result.report, result.report_path)
    if result.exit_code == 1:
        print(output, file=sys.stderr)
    else:
        print(output)
    return result.exit_code


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
        if args.command == "normalize-feed":
            return run_normalize_feed(args)
        if args.command == "match-offers":
            return run_match_offers(args)
        if args.command == "create-candidates":
            return run_create_candidates(args)
        if args.command == "sync-perfume-insert-candidates":
            return run_sync_perfume_insert_candidates(args)
        if args.command == "run-affiliate-pipeline":
            return run_affiliate_pipeline(args)
        if args.command == "inspect-db":
            return run_inspect_db()
        if args.command == "migrate-db":
            return run_migrate_db(args)
        if args.command == "import-local-csv":
            return run_import_local_csv(args)
        if args.command == "import-feeds":
            return run_import_feeds(args)
    except (
        AwinCommandError,
        DbCommandError,
        RawStagingError,
        NormalizationError,
        MatchingError,
        CandidateError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
