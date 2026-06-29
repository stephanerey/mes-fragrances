from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings

SENSITIVE_TOKENS = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "KEY",
    "DATABASE_URL",
    "PGPASSWORD",
)


def _boolish(value: object) -> bool:
    return str(value).strip().lower() == "true"


def _sanitize_header_value(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()


def redact_sensitive_lines(text: str) -> str:
    redacted_lines: list[str] = []
    for line in text.splitlines():
        upper = line.upper()
        if any(token in upper for token in SENSITIVE_TOKENS):
            redacted_lines.append("<redacted>")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines)


def _sanitize_body(text: str) -> str:
    return redact_sensitive_lines(text.replace("\x00", "")).strip() + "\n"


def _sanitize_subject(text: str) -> str:
    return redact_sensitive_lines(_sanitize_header_value(text))


def _locate_sendmail() -> str | None:
    preferred = Path("/usr/sbin/sendmail")
    if preferred.exists():
        return str(preferred)
    return shutil.which("sendmail")


def _locate_mail_command() -> str | None:
    return shutil.which("mail") or shutil.which("mailx")


def _looks_like_r_unsupported(stderr: str, stdout: str) -> bool:
    combined = f"{stderr}\n{stdout}".lower()
    return any(
        token in combined
        for token in (
            "invalid option",
            "unknown option",
            "illegal option",
            "unrecognized option",
            "usage:",
        )
    )


def _send_with_sendmail(message: str, from_addr: str) -> subprocess.CompletedProcess[str]:
    sendmail = _locate_sendmail()
    if not sendmail:
        raise RuntimeError("sendmail is not available")
    return subprocess.run(
        [sendmail, "-t", "-f", _sanitize_subject(from_addr)],
        check=False,
        capture_output=True,
        text=True,
        input=message,
        shell=False,
    )


def _send_with_mail(
    to_addr: str,
    from_addr: str,
    subject: str,
    body: str,
) -> subprocess.CompletedProcess[str]:
    mail_cmd = _locate_mail_command()
    if not mail_cmd:
        raise RuntimeError("mail/mailx is not available")

    first_attempt = subprocess.run(
        [
            mail_cmd,
            "-s",
            _sanitize_subject(subject),
            "-r",
            _sanitize_subject(from_addr),
            _sanitize_subject(to_addr),
        ],
        check=False,
        capture_output=True,
        text=True,
        input=_sanitize_body(body),
        shell=False,
    )
    if first_attempt.returncode == 0:
        return first_attempt

    if _looks_like_r_unsupported(first_attempt.stderr or "", first_attempt.stdout or ""):
        return subprocess.run(
            [mail_cmd, "-s", _sanitize_subject(subject), _sanitize_subject(to_addr)],
            check=False,
            capture_output=True,
            text=True,
            input=f"From: {_sanitize_subject(from_addr)}\n\n{_sanitize_body(body)}",
            shell=False,
        )

    return first_attempt


def _build_subject(prefix: str, status: str, finished_at: str | None) -> str:
    date_part = datetime.now(UTC).strftime("%Y-%m-%d")
    if finished_at:
        try:
            date_part = datetime.fromisoformat(finished_at).date().isoformat()
        except ValueError:
            pass
    return f"{prefix} Pipeline {status} {date_part}"


def _as_int(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    return int(value)


@dataclass(frozen=True)
class AffiliateEmailConfig:
    enabled: bool
    to: str
    from_addr: str
    subject_prefix: str
    send_on_success: bool
    send_on_failure: bool
    command: str


class AffiliateEmailReportService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _load_config(self) -> AffiliateEmailConfig:
        return AffiliateEmailConfig(
            enabled=bool(self.settings.affiliate_email_report_enabled),
            to=str(self.settings.affiliate_email_report_to or "").strip(),
            from_addr=str(self.settings.affiliate_email_report_from or "").strip(),
            subject_prefix=(
                str(self.settings.affiliate_email_report_subject_prefix).strip() or "[Awin]"
            ),
            send_on_success=bool(self.settings.affiliate_email_report_send_on_success),
            send_on_failure=bool(self.settings.affiliate_email_report_send_on_failure),
            command=str(self.settings.affiliate_email_report_command).strip() or "sendmail",
        )

    def _should_send(self, *, status: str, config: AffiliateEmailConfig) -> bool:
        if not config.enabled:
            return False
        lowered = status.lower()
        if lowered == "success":
            return config.send_on_success
        return config.send_on_failure

    def build_pipeline_email_body(
        self,
        report: dict[str, object],
        report_path: Path,
    ) -> str:
        totals = dict(report.get("totals", {}))
        counts = dict(report.get("perfume_insert_candidates_counts", {}))
        safe_top_brands = report.get("safe_top_brands") or []
        lines = [
            f"Status: {report.get('status')}",
            f"Network: {report.get('network')}",
            f"Started at: {report.get('started_at')}",
            f"Finished at: {report.get('finished_at')}",
            f"Report path: {report_path}",
            "",
            "Core metrics:",
            f"  import_run_id: {report.get('latest_import_run_id') or '<n/a>'}",
            f"  normalized_rows_total: {_as_int(totals, 'normalized_rows_total')}",
            f"  rows_matched_total: {_as_int(totals, 'rows_matched_total')}",
            f"  rows_unmatched: {_as_int(totals, 'rows_unmatched')}",
            f"  offers_inserted: {_as_int(totals, 'offers_inserted')}",
            f"  offers_updated: {_as_int(totals, 'offers_updated')}",
            f"  offers_unchanged: {_as_int(totals, 'offers_unchanged')}",
            f"  candidates_created: {_as_int(totals, 'candidates_created')}",
            f"  candidates_updated: {_as_int(totals, 'candidates_updated')}",
            f"  candidates_unchanged: {_as_int(totals, 'candidates_unchanged')}",
            "",
            "Perfume insert candidate sync:",
            f"  staging_inserted: {_as_int(totals, 'staging_inserted')}",
            f"  staging_updated: {_as_int(totals, 'staging_updated')}",
            (
                "  staging_ignored_manual_status: "
                f"{_as_int(totals, 'staging_ignored_manual_status')}"
            ),
            f"  safe_new_candidates_count: {_as_int(totals, 'safe_new_candidates_count')}",
            "",
            "Refresh dry-run:",
            f"  candidates_loaded: {_as_int(totals, 'refresh_candidates_loaded')}",
            (f"  candidates_would_update: {_as_int(totals, 'refresh_candidates_would_update')}"),
            (f"  candidates_without_match: {_as_int(totals, 'refresh_candidates_without_match')}"),
            f"  candidates_unchanged: {_as_int(totals, 'refresh_candidates_unchanged')}",
            "",
            "Staging counts:",
            f"  pending: {counts.get('pending', 0)}",
            f"  promoted: {counts.get('promoted', 0)}",
            f"  approved: {counts.get('approved', 0)}",
        ]
        if safe_top_brands:
            lines.extend(["", "Top SAFE brands:"])
            for row in safe_top_brands[:10]:
                lines.append(f"  {row.get('candidate_brand', '<missing>')}: {row.get('count', 0)}")

        csv_paths: list[str] = []
        for feed in report.get("feeds", []):
            if not isinstance(feed, dict):
                continue
            steps = dict(feed.get("steps", {}))
            sync_step = dict(steps.get("candidate_sync", {}))
            refresh_step = dict(steps.get("refresh_dry_run", {}))
            safe_csv_path = sync_step.get("safe_csv_path")
            refresh_csv_path = refresh_step.get("csv_report_path")
            if isinstance(safe_csv_path, str) and safe_csv_path:
                csv_paths.append(safe_csv_path)
            if isinstance(refresh_csv_path, str) and refresh_csv_path:
                csv_paths.append(refresh_csv_path)
        if csv_paths:
            lines.extend(["", "Useful CSV paths:"])
            for path in csv_paths[:10]:
                lines.append(f"  {path}")

        warnings = report.get("warnings") or []
        if warnings:
            lines.extend(["", "Warnings:"])
            for warning in warnings[:20]:
                lines.append(f"  - {warning}")

        return _sanitize_body("\n".join(lines))

    def send_text_email(
        self,
        *,
        subject: str,
        body: str,
        force_enabled: bool | None = None,
    ) -> dict[str, object]:
        config = self._load_config()
        enabled = config.enabled if force_enabled is None else force_enabled
        config = AffiliateEmailConfig(
            enabled=enabled,
            to=config.to,
            from_addr=config.from_addr,
            subject_prefix=config.subject_prefix,
            send_on_success=config.send_on_success,
            send_on_failure=config.send_on_failure,
            command=config.command,
        )
        result: dict[str, object] = {
            "attempted": False,
            "success": False,
            "skipped": True,
            "command": config.command,
            "enabled": config.enabled,
            "subject": _sanitize_subject(subject),
            "recipient_configured": bool(config.to),
            "sender_configured": bool(config.from_addr),
            "error": "",
        }
        if not config.enabled:
            result["skip_reason"] = "Email disabled by configuration."
            return result

        result["attempted"] = True
        result["skipped"] = False
        if not config.to:
            result["error"] = "AFFILIATE_EMAIL_REPORT_TO is missing."
            return result
        if not config.from_addr:
            result["error"] = "AFFILIATE_EMAIL_REPORT_FROM is missing."
            return result
        if config.command not in {"sendmail", "mail"}:
            result["error"] = "AFFILIATE_EMAIL_REPORT_COMMAND must be 'sendmail' or 'mail'."
            return result

        try:
            if config.command == "sendmail":
                message = (
                    f"To: {_sanitize_subject(config.to)}\n"
                    f"From: {_sanitize_subject(config.from_addr)}\n"
                    f"Subject: {result['subject']}\n"
                    "MIME-Version: 1.0\n"
                    "Content-Type: text/plain; charset=UTF-8\n"
                    "\n"
                    f"{_sanitize_body(body)}"
                )
                completed = _send_with_sendmail(message, config.from_addr)
            else:
                completed = _send_with_mail(
                    config.to,
                    config.from_addr,
                    str(result["subject"]),
                    body,
                )
        except Exception as exc:  # pragma: no cover - defensive path
            result["error"] = str(exc)
            return result

        if completed.returncode != 0:
            result["error"] = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"{config.command} exited with {completed.returncode}"
            )
            return result

        result["success"] = True
        result["hostname"] = socket.gethostname()
        return result

    def send_pipeline_report(
        self,
        report: dict[str, object],
        report_path: Path,
        *,
        force_enabled: bool | None = None,
    ) -> dict[str, object]:
        config = self._load_config()
        enabled = config.enabled if force_enabled is None else force_enabled
        config = AffiliateEmailConfig(
            enabled=enabled,
            to=config.to,
            from_addr=config.from_addr,
            subject_prefix=config.subject_prefix,
            send_on_success=config.send_on_success,
            send_on_failure=config.send_on_failure,
            command=config.command,
        )
        status = str(report.get("status", "failed"))
        attempted = self._should_send(status=status, config=config)
        result: dict[str, object] = {
            "attempted": attempted,
            "success": False,
            "skipped": not attempted,
            "command": config.command,
            "enabled": config.enabled,
            "subject": "",
            "recipient_configured": bool(config.to),
            "sender_configured": bool(config.from_addr),
            "error": "",
        }
        if not attempted:
            result["skip_reason"] = "Email disabled by configuration or send policy."
            return result

        if not config.to:
            result["error"] = "AFFILIATE_EMAIL_REPORT_TO is missing."
            return result
        if not config.from_addr:
            result["error"] = "AFFILIATE_EMAIL_REPORT_FROM is missing."
            return result
        if config.command not in {"sendmail", "mail"}:
            result["error"] = "AFFILIATE_EMAIL_REPORT_COMMAND must be 'sendmail' or 'mail'."
            return result

        return self.send_text_email(
            subject=_build_subject(
                config.subject_prefix,
                status=status,
                finished_at=str(report.get("finished_at") or ""),
            ),
            body=self.build_pipeline_email_body(report, report_path),
            force_enabled=config.enabled,
        )
