from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping

import psycopg

from app.config import Settings
from app.email_report import AffiliateEmailReportService


class DigestError(Exception):
    """Raised when digest generation cannot complete."""


BIG_BRANDS = {
    "CALVIN KLEIN",
    "DOLCE & GABANNA",
    "GIORGIO ARMANI",
    "HUGO BOSS",
    "ISSEY MIYAKE",
    "JEAN PAUL GAULTIER",
    "KENZO",
    "MUGLER",
    "NARCISO RODRIGUEZ",
    "NINA RICCI",
    "PACO RABANNE",
    "PRADA",
    "YVES SAINT LAURENT",
}

STRICT_NON_PERFUME_PATTERN = (
    r"(coffret|\mset\M|discovery|sample|tester|refill|recharge|bougie|candle|"
    r"\mbody\M|lotion|shower gel|gel douche|savon|\msoap\M|after shave|"
    r"diffuseur|home fragrance)"
)
ACTIONABLE_REVIEW_PATTERN = r"(discovery|\mset\M|bundle|sample|tester|coffret)"
EXCLUDED_MATCH_REASON_PATTERN = "%excluded_set_or_bundle%"


@dataclass(frozen=True)
class FeedKey:
    network: str
    advertiser_id: str
    feed_id: str


def _as_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return 0


def _normalize_warning(message: object) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    return " ".join(text.split())


def _slugify(value: str) -> str:
    cleaned = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
            previous_dash = False
            continue
        if not previous_dash:
            cleaned.append("-")
            previous_dash = True
    return "".join(cleaned).strip("-") or "digest"


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _backlog_unavailable(reason: str | None = None) -> dict[str, object]:
    warnings = []
    if reason:
        warnings.append(f"Backlog snapshot unavailable: {reason}")
    return {"available": False, "warnings": warnings}


def _backlog_unavailable_reason(backlog: Mapping[str, object]) -> str | None:
    warnings = backlog.get("warnings") or []
    if not warnings:
        return None
    warning = str(warnings[0]).strip()
    prefix = "Backlog snapshot unavailable:"
    if warning.startswith(prefix):
        return warning[len(prefix) :].strip()
    return warning or None


class AffiliateDigestService:
    def __init__(
        self,
        settings: Settings,
        *,
        now_fn: Callable[[], datetime] | None = None,
        email_service: AffiliateEmailReportService | None = None,
    ) -> None:
        self.settings = settings
        self.now_fn = now_fn or (lambda: datetime.now(UTC))
        self.email_service = email_service or AffiliateEmailReportService(settings)

    def generate_digest(
        self,
        *,
        reports_root: Path,
        since_days: int,
        locale: str,
        output_dir: Path | None,
        email_subject: str | None,
        dry_run: bool,
        send_email: bool,
    ) -> tuple[dict[str, object], Path]:
        if since_days <= 0:
            raise DigestError("--since-days must be greater than 0")
        locale = locale.strip().lower()
        if locale != "fr":
            raise DigestError("Only locale 'fr' is supported for this digest")

        resolved_reports_root = reports_root.expanduser().resolve()
        if not resolved_reports_root.exists():
            raise DigestError(f"Reports root does not exist: {resolved_reports_root}")

        now = self.now_fn()
        cutoff = now - timedelta(days=since_days)
        selected_reports = self._select_pipeline_reports(resolved_reports_root, cutoff)
        if not selected_reports:
            raise DigestError(
                "No affiliate pipeline report found in "
                f"{resolved_reports_root} for the last {since_days} days"
            )

        generated_at = now.strftime("%Y%m%dT%H%M%SZ")
        effective_output_dir = (
            output_dir.expanduser().resolve()
            if output_dir is not None
            else self.settings.reports_dir / f"affiliate_digest_{generated_at}"
        )
        effective_output_dir.mkdir(parents=True, exist_ok=True)

        summary = self._build_digest_summary(
            selected_reports=selected_reports,
            reports_root=resolved_reports_root,
            since_days=since_days,
            locale=locale,
            generated_at=now,
            output_dir=effective_output_dir,
            requested_email_subject=email_subject,
        )
        summary["dry_run"] = dry_run

        markdown_path = effective_output_dir / summary["markdown_filename"]
        json_path = effective_output_dir / summary["json_filename"]
        markdown_body = self._render_markdown(summary)
        markdown_path.write_text(markdown_body, encoding="utf-8")

        summary["markdown_report_path"] = str(markdown_path)
        summary["email_subject"] = email_subject or self._default_email_subject(summary)
        summary["email_report"] = {
            "attempted": False,
            "success": False,
            "skipped": True,
            "skip_reason": "Digest email disabled for this run.",
        }

        if send_email and not dry_run:
            summary["email_report"] = self.email_service.send_text_email(
                subject=str(summary["email_subject"]),
                body=markdown_body,
            )
            if summary["email_report"].get("attempted") and not summary["email_report"].get(
                "success"
            ):
                summary.setdefault("warnings", []).append(
                    "Digest email delivery failed: "
                    f"{summary['email_report'].get('error', 'unknown error')}"
                )
        elif send_email and dry_run:
            summary["email_report"] = {
                "attempted": False,
                "success": False,
                "skipped": True,
                "skip_reason": "Digest email skipped because --dry-run is enabled.",
            }

        json_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return summary, json_path

    def _select_pipeline_reports(
        self,
        reports_root: Path,
        cutoff: datetime,
    ) -> list[tuple[Path, dict[str, object]]]:
        selected: list[tuple[Path, dict[str, object]]] = []
        for path in sorted(reports_root.glob("affiliate_pipeline_*.json")):
            if path.name == "latest_affiliate_pipeline_report.json":
                continue
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            started_at = _parse_timestamp(report.get("started_at"))
            if started_at is None or started_at < cutoff:
                continue
            selected.append((path, report))
        return selected

    def _build_digest_summary(
        self,
        *,
        selected_reports: list[tuple[Path, dict[str, object]]],
        reports_root: Path,
        since_days: int,
        locale: str,
        generated_at: datetime,
        output_dir: Path,
        requested_email_subject: str | None,
    ) -> dict[str, object]:
        feed_groups: dict[FeedKey, dict[str, object]] = {}
        overall_warnings = Counter()
        overall_errors = Counter()
        failed_runs: list[dict[str, object]] = []
        period_start: datetime | None = None
        period_end: datetime | None = None

        overall_metrics = {
            "runs_total": 0,
            "runs_success": 0,
            "runs_failed": 0,
            "offers_inserted": 0,
            "offers_updated": 0,
            "offers_unchanged": 0,
            "candidates_created": 0,
            "candidates_updated": 0,
            "candidates_unchanged": 0,
            "safe_new_candidates_count": 0,
            "refresh_candidates_would_update": 0,
            "refresh_candidates_without_match": 0,
            "refresh_candidates_loaded": 0,
            "rows_errors": 0,
        }

        for report_path, report in selected_reports:
            started_at = _parse_timestamp(report.get("started_at"))
            finished_at = _parse_timestamp(report.get("finished_at"))
            if started_at is None:
                continue
            period_start = started_at if period_start is None else min(period_start, started_at)
            if finished_at is not None:
                period_end = finished_at if period_end is None else max(period_end, finished_at)
            report_status = str(report.get("status") or "unknown")
            overall_metrics["runs_total"] += 1
            if report_status == "success":
                overall_metrics["runs_success"] += 1
            else:
                overall_metrics["runs_failed"] += 1

            feeds = report.get("feeds")
            if not isinstance(feeds, list) or not feeds:
                feeds = [
                    {
                        "network": report.get("network"),
                        "advertiser_id": "",
                        "advertiser_name": "<unknown advertiser>",
                        "feed_id": "",
                        "status": report.get("status"),
                        "summary": report.get("totals") or {},
                        "steps": {},
                        "warnings": report.get("warnings") or [],
                    }
                ]

            for feed in feeds:
                if not isinstance(feed, Mapping):
                    continue
                started_label = started_at.date().isoformat()
                network = str(feed.get("network") or report.get("network") or "awin")
                advertiser_id = str(feed.get("advertiser_id") or "")
                advertiser_name = str(feed.get("advertiser_name") or "<unknown advertiser>")
                feed_id = str(feed.get("feed_id") or "")
                status = str(feed.get("status") or report.get("status") or "unknown")
                summary = dict(feed.get("summary") or {})
                steps = dict(feed.get("steps") or {})

                warnings = []
                for item in report.get("warnings") or []:
                    text = _normalize_warning(item)
                    if text:
                        warnings.append(text)
                for item in feed.get("warnings") or []:
                    text = _normalize_warning(item)
                    if text:
                        warnings.append(text)

                errors = []
                for step_name, step in steps.items():
                    if not isinstance(step, Mapping):
                        continue
                    error = _normalize_warning(step.get("error"))
                    if error:
                        errors.append(f"{step_name}: {error}")

                key = FeedKey(network=network, advertiser_id=advertiser_id, feed_id=feed_id)
                if key not in feed_groups:
                    feed_groups[key] = {
                        "network": network,
                        "advertiser_id": advertiser_id,
                        "advertiser_name": advertiser_name,
                        "feed_id": feed_id,
                        "runs_total": 0,
                        "runs_success": 0,
                        "runs_failed": 0,
                        "metrics": defaultdict(int),
                        "warnings": Counter(),
                        "errors": Counter(),
                        "daily_runs": [],
                    }

                aggregate = feed_groups[key]
                aggregate["runs_total"] += 1
                if status == "success":
                    aggregate["runs_success"] += 1
                else:
                    aggregate["runs_failed"] += 1

                daily_metrics = {
                    "date": started_label,
                    "status": status,
                    "report_path": str(report_path),
                    "import_run_id": summary.get("import_run_id"),
                    "offers_inserted": _as_int(summary.get("offers_inserted")),
                    "offers_updated": _as_int(summary.get("offers_updated")),
                    "candidates_created": _as_int(summary.get("candidates_created")),
                    "safe_new_candidates_count": _as_int(summary.get("safe_new_candidates_count")),
                    "refresh_candidates_would_update": _as_int(
                        summary.get("refresh_candidates_would_update")
                    ),
                    "warnings": warnings,
                    "errors": errors,
                }
                aggregate["daily_runs"].append(daily_metrics)

                metric_fields = (
                    "offers_inserted",
                    "offers_updated",
                    "offers_unchanged",
                    "candidates_created",
                    "candidates_updated",
                    "candidates_unchanged",
                    "safe_new_candidates_count",
                    "refresh_candidates_would_update",
                    "refresh_candidates_without_match",
                    "refresh_candidates_loaded",
                    "rows_errors",
                )
                for field in metric_fields:
                    value = _as_int(summary.get(field))
                    aggregate["metrics"][field] += value
                    overall_metrics[field] += value

                for warning in warnings:
                    aggregate["warnings"][warning] += 1
                    overall_warnings[warning] += 1
                for error in errors:
                    aggregate["errors"][error] += 1
                    overall_errors[error] += 1
                if status != "success":
                    failed_runs.append(
                        {
                            "date": started_label,
                            "network": network,
                            "advertiser_id": advertiser_id,
                            "advertiser_name": advertiser_name,
                            "feed_id": feed_id,
                            "report_path": str(report_path),
                            "errors": errors,
                            "warnings": warnings,
                        }
                    )

        if not feed_groups:
            raise DigestError("No digestable feed report found in the selected window")

        backlog = self._load_backlog_snapshot()
        feeds_payload = []
        for key in sorted(
            feed_groups,
            key=lambda item: (
                feed_groups[item]["advertiser_name"],
                item.advertiser_id,
                item.feed_id,
                item.network,
            ),
        ):
            aggregate = feed_groups[key]
            daily_runs = sorted(
                aggregate["daily_runs"],
                key=lambda row: row["date"],
                reverse=True,
            )
            feeds_payload.append(
                {
                    "network": aggregate["network"],
                    "advertiser_id": aggregate["advertiser_id"],
                    "advertiser_name": aggregate["advertiser_name"],
                    "feed_id": aggregate["feed_id"],
                    "runs_total": aggregate["runs_total"],
                    "runs_success": aggregate["runs_success"],
                    "runs_failed": aggregate["runs_failed"],
                    "metrics": dict(aggregate["metrics"]),
                    "warnings_top": [
                        {"message": message, "count": count}
                        for message, count in aggregate["warnings"].most_common(5)
                    ],
                    "errors_top": [
                        {"message": message, "count": count}
                        for message, count in aggregate["errors"].most_common(5)
                    ],
                    "daily_runs": daily_runs,
                }
            )

        summary = {
            "command": "digest-reports",
            "status": "success",
            "locale": locale,
            "dry_run": False,
            "reports_root": str(reports_root),
            "output_dir": str(output_dir),
            "generated_at": generated_at.isoformat(),
            "since_days": since_days,
            "period_start": period_start.date().isoformat() if period_start else None,
            "period_end": (
                (period_end or period_start).date().isoformat() if period_start else None
            ),
            "metrics": overall_metrics,
            "failed_runs": failed_runs,
            "warnings_top": [
                {"message": message, "count": count}
                for message, count in overall_warnings.most_common(10)
            ],
            "errors_top": [
                {"message": message, "count": count}
                for message, count in overall_errors.most_common(10)
            ],
            "backlog": backlog,
            "feeds": feeds_payload,
            "recommendations": self._build_recommendations(
                overall_metrics=overall_metrics,
                backlog=backlog,
                failed_runs=failed_runs,
                feeds=feeds_payload,
            ),
            "warnings": list(backlog.get("warnings", [])),
            "json_filename": self._build_filename(
                prefix="affiliate_digest",
                locale=locale,
                extension="json",
                generated_at=generated_at,
            ),
            "markdown_filename": self._build_filename(
                prefix="affiliate_digest",
                locale=locale,
                extension="md",
                generated_at=generated_at,
            ),
        }
        if failed_runs:
            summary["status"] = "warning"
        if requested_email_subject:
            summary["email_subject"] = requested_email_subject
        return summary

    def _build_filename(
        self,
        *,
        prefix: str,
        locale: str,
        extension: str,
        generated_at: datetime,
    ) -> str:
        timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
        return f"{prefix}_{_slugify(locale)}_{timestamp}.{extension}"

    def _default_email_subject(self, report: Mapping[str, object]) -> str:
        prefix = "[Awin Digest]"
        period_start = report.get("period_start") or "<unknown>"
        period_end = report.get("period_end") or "<unknown>"
        status_label = (
            "Alerte" if _as_int(dict(report.get("metrics", {})).get("runs_failed")) else "Digest"
        )
        return f"{prefix} {status_label} hebdomadaire {period_start} -> {period_end}"

    def _render_markdown(self, report: Mapping[str, object]) -> str:
        metrics = dict(report.get("metrics", {}))
        backlog = dict(report.get("backlog", {}))
        lines = [
            "# Digest affilié hebdomadaire",
            "",
            f"- Période couverte : `{report.get('period_start')}` -> `{report.get('period_end')}`",
            f"- Généré le : `{report.get('generated_at')}`",
            f"- Fenêtre d'analyse : `{report.get('since_days')}` jours",
            "",
            "## Vue d'ensemble",
            (
                "- Runs OK / failed : "
                f"`{metrics.get('runs_success', 0)}` / "
                f"`{metrics.get('runs_failed', 0)}`"
            ),
            f"- Offres créées : `{metrics.get('offers_inserted', 0)}`",
            f"- Offres mises à jour : `{metrics.get('offers_updated', 0)}`",
            f"- Candidats créés : `{metrics.get('candidates_created', 0)}`",
            f"- Candidats mis à jour : `{metrics.get('candidates_updated', 0)}`",
            f"- Nouveaux SAFE : `{metrics.get('safe_new_candidates_count', 0)}`",
            (
                "- Refresh candidates : "
                f"`loaded={metrics.get('refresh_candidates_loaded', 0)}` / "
                f"`would_update={metrics.get('refresh_candidates_would_update', 0)}` / "
                f"`without_match={metrics.get('refresh_candidates_without_match', 0)}`"
            ),
            f"- Erreurs de lignes : `{metrics.get('rows_errors', 0)}`",
        ]

        if backlog.get("available"):
            lines.extend(
                [
                    "",
                    "## État backlog",
                    f"- Strict restant : `{backlog.get('strict_remaining_total', 0)}`",
                    (
                        "- `needs_review` actionnables : "
                        f"`{backlog.get('needs_review_actionable_total', 0)}`"
                    ),
                    (
                        "- `product_match_candidates.pending` : "
                        f"`{backlog.get('product_match_pending_total', 0)}`"
                    ),
                    (
                        "- `product_match_candidates.accepted_existing_perfume` : "
                        f"`{backlog.get('accepted_existing_perfume_total', 0)}`"
                    ),
                ]
            )
        else:
            backlog_reason = _backlog_unavailable_reason(backlog)
            lines.extend(
                [
                    "",
                    "## État backlog",
                    (
                        "- Backlog indisponible : "
                        f"`{backlog_reason}`"
                        if backlog_reason
                        else "- Snapshot backlog indisponible dans ce contexte."
                    ),
                ]
            )

        warnings_top = report.get("warnings_top") or []
        errors_top = report.get("errors_top") or []
        lines.extend(["", "## Alertes et warnings"])
        if errors_top:
            lines.append("- Erreurs récurrentes :")
            for row in errors_top:
                if not isinstance(row, Mapping):
                    continue
                lines.append(
                    f"  - `{row.get('count', 0)}x` {row.get('message', '<missing error>')}"
                )
        if warnings_top:
            lines.append("- Warnings récurrents :")
            for row in warnings_top:
                if not isinstance(row, Mapping):
                    continue
                lines.append(
                    f"  - `{row.get('count', 0)}x` {row.get('message', '<missing warning>')}"
                )
        if not warnings_top and not errors_top:
            lines.append("- Aucun warning récurrent notable.")

        failed_runs = report.get("failed_runs") or []
        if failed_runs:
            lines.extend(["", "## Runs en échec"])
            for row in failed_runs:
                if not isinstance(row, Mapping):
                    continue
                lines.append(
                    "- "
                    f"`{row.get('date')}` `{row.get('advertiser_name')}` "
                    f"(feed `{row.get('feed_id')}`) : "
                    f"{'; '.join(row.get('errors') or row.get('warnings') or ['<no detail>'])}"
                )

        lines.extend(["", "## Par advertiser / feed"])
        for feed in report.get("feeds", []):
            if not isinstance(feed, Mapping):
                continue
            feed_metrics = dict(feed.get("metrics", {}))
            title = (
                f"### {feed.get('advertiser_name')} "
                f"(`{feed.get('network')}` / advertiser `{feed.get('advertiser_id')}` / "
                f"feed `{feed.get('feed_id')}`)"
            )
            lines.extend(
                [
                    title,
                    (
                        "- Runs OK / failed : "
                        f"`{feed.get('runs_success', 0)}` / "
                        f"`{feed.get('runs_failed', 0)}`"
                    ),
                    (
                        "- Offres créées / mises à jour : "
                        f"`{feed_metrics.get('offers_inserted', 0)}` / "
                        f"`{feed_metrics.get('offers_updated', 0)}`"
                    ),
                    (
                        "- Candidats créés / SAFE : "
                        f"`{feed_metrics.get('candidates_created', 0)}` / "
                        f"`{feed_metrics.get('safe_new_candidates_count', 0)}`"
                    ),
                    (
                        "- Refresh dry-run : "
                        f"`would_update="
                        f"{feed_metrics.get('refresh_candidates_would_update', 0)}` / "
                        f"`without_match={feed_metrics.get('refresh_candidates_without_match', 0)}`"
                    ),
                    "",
                    "| Date | Statut | Offres + | Candidats + | SAFE | Refresh |",
                    "| --- | --- | ---: | ---: | ---: | ---: |",
                ]
            )
            for row in feed.get("daily_runs", [])[:7]:
                if not isinstance(row, Mapping):
                    continue
                lines.append(
                    "| "
                    f"{row.get('date')} | {row.get('status')} | {row.get('offers_updated', 0)} | "
                    f"{row.get('candidates_created', 0)} | "
                    f"{row.get('safe_new_candidates_count', 0)} | "
                    f"{row.get('refresh_candidates_would_update', 0)} |"
                )
            if feed.get("errors_top"):
                lines.append("")
                lines.append("- Erreurs feed :")
                for row in feed["errors_top"]:
                    if not isinstance(row, Mapping):
                        continue
                    lines.append(
                        f"  - `{row.get('count', 0)}x` {row.get('message', '<missing error>')}"
                    )
            if feed.get("warnings_top"):
                lines.append("")
                lines.append("- Warnings feed :")
                for row in feed["warnings_top"]:
                    if not isinstance(row, Mapping):
                        continue
                    lines.append(
                        f"  - `{row.get('count', 0)}x` {row.get('message', '<missing warning>')}"
                    )
            lines.append("")

        lines.extend(["## Recommandations automatiques"])
        recommendations = report.get("recommendations") or []
        if recommendations:
            for recommendation in recommendations:
                lines.append(f"- {recommendation}")
        else:
            lines.append("- Aucun signal automatique supplémentaire.")
        lines.append("")
        return "\n".join(lines)

    def _build_recommendations(
        self,
        *,
        overall_metrics: Mapping[str, int],
        backlog: Mapping[str, object],
        failed_runs: list[dict[str, object]],
        feeds: list[dict[str, object]],
    ) -> list[str]:
        recommendations: list[str] = []
        if failed_runs:
            recommendations.append(
                "Conserver l'alerte immédiate sur échec critique: "
                "au moins un run a échoué dans la fenêtre."
            )
        else:
            recommendations.append(
                "Les succès quotidiens peuvent rester en fichiers uniquement; "
                "aucun email quotidien de succès n'est nécessaire."
            )
        if _as_int(backlog.get("strict_remaining_total")) >= 400:
            recommendations.append(
                "Le backlog strict reste élevé: préparer un fast path borné sur "
                "les SAFE low-risk avant l'ajout de nouveaux annonceurs."
            )
        if _as_int(backlog.get("needs_review_actionable_total")) >= 20:
            recommendations.append(
                "Le stock de `needs_review` actionnables justifie une revue ciblée "
                "ou une automatisation progressive par marque."
            )
        if overall_metrics.get("safe_new_candidates_count", 0) == 0:
            recommendations.append(
                "Aucun nouveau SAFE n'a été détecté sur la période: vérifier la "
                "qualité du matching et des règles de classification."
            )
        if any(feed.get("runs_failed", 0) for feed in feeds):
            recommendations.append(
                "Le format multi-feed est prêt: garder une section par "
                "advertiser/feed dans le digest avant d'activer Flaconi FR."
            )
        return recommendations

    def _load_backlog_snapshot(self) -> dict[str, object]:
        database_url = self.settings.database_url
        if database_url is None or not database_url.get_secret_value():
            return _backlog_unavailable(
                "DATABASE_URL absent: snapshot backlog lecture seule non disponible."
            )

        try:
            with psycopg.connect(database_url.get_secret_value()) as conn:
                with conn.cursor() as cur:
                    cur.execute("BEGIN READ ONLY")
                    cur.execute("SELECT count(*) FROM public.perfumes")
                    perfumes_total = _as_int(cur.fetchone()[0])
                    cur.execute("SELECT count(*) FROM public.offers")
                    offers_total = _as_int(cur.fetchone()[0])
                    cur.execute(
                        """
                        SELECT COALESCE(review_status, '<null>'), count(*)
                        FROM public.perfume_insert_candidates
                        GROUP BY 1
                        """
                    )
                    review_status_counts = {
                        str(status): _as_int(count) for status, count in cur.fetchall()
                    }
                    cur.execute(
                        """
                        SELECT COALESCE(status, '<null>'), count(*)
                        FROM public.product_match_candidates
                        GROUP BY 1
                        """
                    )
                    pmc_status_counts = {
                        str(status): _as_int(count) for status, count in cur.fetchall()
                    }
                    cur.execute(
                        """
                        WITH existing_exact AS (
                          SELECT lower(btrim(brand)) AS brand_norm, lower(btrim(name)) AS name_norm
                          FROM public.perfumes
                        )
                        SELECT count(*)
                        FROM public.perfume_insert_candidates c
                        WHERE c.review_status = 'pending'
                          AND c.classification = 'SAFE_INSERT_CANDIDATE'
                          AND c.duplicate_risk = 'low'
                          AND COALESCE(btrim(c.candidate_brand), '') <> ''
                          AND COALESCE(btrim(c.candidate_name), '') <> ''
                          AND COALESCE(btrim(c.candidate_image_url), '') <> ''
                          AND (
                            COALESCE(btrim(c.candidate_ean), '') <> ''
                            OR COALESCE(btrim(c.candidate_gtin), '') <> ''
                            OR COALESCE(btrim(c.candidate_upc), '') <> ''
                            OR COALESCE(btrim(c.candidate_mpn), '') <> ''
                          )
                          AND NOT EXISTS (
                            SELECT 1
                            FROM existing_exact e
                            WHERE e.brand_norm = lower(btrim(c.candidate_brand))
                              AND e.name_norm = lower(btrim(c.candidate_name))
                          )
                          AND NOT EXISTS (
                            SELECT 1
                            FROM public.perfumes p
                            WHERE (
                              COALESCE(btrim(c.candidate_ean), '') <> ''
                              AND p.ean = btrim(c.candidate_ean)
                            )
                            OR (
                              COALESCE(btrim(c.candidate_gtin), '') <> ''
                              AND p.gtin = btrim(c.candidate_gtin)
                            )
                            OR (
                              COALESCE(btrim(c.candidate_upc), '') <> ''
                              AND p.upc = btrim(c.candidate_upc)
                            )
                            OR (
                              COALESCE(btrim(c.candidate_mpn), '') <> ''
                              AND p.mpn = btrim(c.candidate_mpn)
                            )
                          )
                          AND c.candidate_name !~* %(strict_non_perfume_pattern)s
                        """,
                        {"strict_non_perfume_pattern": STRICT_NON_PERFUME_PATTERN},
                    )
                    strict_remaining_total = _as_int(cur.fetchone()[0])
                    cur.execute(
                        """
                        SELECT count(*)
                        FROM public.product_match_candidates pmc
                        WHERE pmc.status = 'needs_review'
                          AND pmc.proposed_perfume_id IS NOT NULL
                          AND COALESCE(
                            NULLIF(btrim(pmc.enrichment_payload->>'affiliate_url'), ''),
                            ''
                          ) <> ''
                          AND COALESCE(
                            NULLIF(btrim(pmc.enrichment_payload->>'price'), ''),
                            ''
                          ) <> ''
                          AND COALESCE(
                            NULLIF(btrim(pmc.enrichment_payload->>'currency'), ''),
                            ''
                          ) <> ''
                          AND (
                            COALESCE(
                              NULLIF(btrim(pmc.enrichment_payload->>'network_product_id'), ''),
                              ''
                            ) <> ''
                            OR COALESCE(
                              NULLIF(btrim(pmc.enrichment_payload->>'merchant_product_id'), ''),
                              ''
                            ) <> ''
                          )
                          AND pmc.candidate_name !~* %(actionable_review_pattern)s
                          AND COALESCE(pmc.match_reason, '') NOT ILIKE
                            %(excluded_match_reason_pattern)s
                          AND NOT (
                            upper(COALESCE(btrim(pmc.candidate_brand), '')) = ANY(%(big_brands)s)
                          )
                          AND NOT EXISTS (
                            SELECT 1
                            FROM public.offers o
                            WHERE (
                              COALESCE(
                                NULLIF(btrim(pmc.enrichment_payload->>'network_product_id'), ''),
                                ''
                              ) <> ''
                              AND o.network_product_id = NULLIF(
                                btrim(pmc.enrichment_payload->>'network_product_id'),
                                ''
                              )
                            )
                            OR (
                              COALESCE(
                                NULLIF(btrim(pmc.enrichment_payload->>'merchant_product_id'), ''),
                                ''
                              ) <> ''
                              AND o.merchant_product_id = NULLIF(
                                btrim(pmc.enrichment_payload->>'merchant_product_id'),
                                ''
                              )
                            )
                            OR (
                              COALESCE(
                                NULLIF(btrim(pmc.enrichment_payload->>'affiliate_url'), ''),
                                ''
                              ) <> ''
                              AND o.affiliate_url = NULLIF(
                                btrim(pmc.enrichment_payload->>'affiliate_url'),
                                ''
                              )
                            )
                          )
                        """,
                        {
                            "actionable_review_pattern": ACTIONABLE_REVIEW_PATTERN,
                            "excluded_match_reason_pattern": EXCLUDED_MATCH_REASON_PATTERN,
                            "big_brands": sorted(BIG_BRANDS),
                        },
                    )
                    needs_review_actionable_total = _as_int(cur.fetchone()[0])
                    cur.execute("ROLLBACK")
        except Exception as exc:
            return _backlog_unavailable(str(exc))

        return {
            "available": True,
            "perfumes_total": perfumes_total,
            "offers_total": offers_total,
            "perfume_insert_review_status_counts": review_status_counts,
            "product_match_status_counts": pmc_status_counts,
            "strict_remaining_total": strict_remaining_total,
            "needs_review_actionable_total": needs_review_actionable_total,
            "product_match_pending_total": pmc_status_counts.get("pending", 0),
            "accepted_existing_perfume_total": pmc_status_counts.get(
                "accepted_existing_perfume", 0
            ),
            "warnings": [],
        }


def format_digest_report_summary(report: Mapping[str, object], report_path: Path) -> str:
    metrics = dict(report.get("metrics", {}))
    email_report = dict(report.get("email_report", {}))
    lines = [
        f"status={report.get('status')}",
        f"locale={report.get('locale')}",
        f"period_start={report.get('period_start')}",
        f"period_end={report.get('period_end')}",
        f"runs_total={metrics.get('runs_total', 0)}",
        f"runs_failed={metrics.get('runs_failed', 0)}",
        f"feeds_total={len(report.get('feeds', []))}",
        f"offers_inserted={metrics.get('offers_inserted', 0)}",
        f"offers_updated={metrics.get('offers_updated', 0)}",
        f"candidates_created={metrics.get('candidates_created', 0)}",
        f"safe_new_candidates_count={metrics.get('safe_new_candidates_count', 0)}",
        f"email_subject={report.get('email_subject', '')}",
        f"markdown_report_path={report.get('markdown_report_path', '')}",
        f"json_report_path={report_path}",
    ]
    if email_report:
        lines.append(f"email_attempted={email_report.get('attempted')}")
        lines.append(f"email_success={email_report.get('success')}")
    return "\n".join(lines)
