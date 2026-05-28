#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/eva/mes-fragrances}"
DOCKER_BIN="${DOCKER_BIN:-/usr/bin/docker}"
WORKER_IMAGE="${WORKER_IMAGE:-mes-fragrances-affiliate-worker}"
WORKER_ENV_FILE="${WORKER_ENV_FILE:-$ROOT_DIR/affiliate-worker/.env}"
DATA_DIR="${DATA_DIR:-$ROOT_DIR/affiliate-worker-data}"
REPORT_ROOT="${REPORT_ROOT:-$DATA_DIR/reports}"
LATEST_REPORT_PATH="${LATEST_REPORT_PATH:-$REPORT_ROOT/latest_affiliate_pipeline_report.json}"
DOCKER_NETWORK="${AFFILIATE_DOCKER_NETWORK:-mes-fragrances_cis_default}"
DEFAULT_PIPELINE_NETWORK="${AFFILIATE_PIPELINE_NETWORK:-awin}"

EMAIL_ENABLED="${AFFILIATE_HOST_EMAIL_REPORT_ENABLED:-false}"
EMAIL_TO="${AFFILIATE_HOST_EMAIL_REPORT_TO:-}"
EMAIL_FROM="${AFFILIATE_HOST_EMAIL_REPORT_FROM:-}"
EMAIL_SUBJECT_PREFIX="${AFFILIATE_HOST_EMAIL_REPORT_SUBJECT_PREFIX:-[Awin]}"
EMAIL_SEND_ON_SUCCESS="${AFFILIATE_HOST_EMAIL_REPORT_SEND_ON_SUCCESS:-false}"
EMAIL_SEND_ON_FAILURE="${AFFILIATE_HOST_EMAIL_REPORT_SEND_ON_FAILURE:-false}"
EMAIL_COMMAND="${AFFILIATE_HOST_EMAIL_REPORT_COMMAND:-sendmail}"

log() {
  printf '%s\n' "$*"
}

warn() {
  printf 'warning: %s\n' "$*" >&2
}

is_true() {
  case "${1,,}" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

build_pipeline_args() {
  if [ "$#" -eq 0 ]; then
    printf '%s\n' --network "$DEFAULT_PIPELINE_NETWORK"
    return
  fi

  printf '%s\n' "$@"
}

write_email_files() {
  local report_path="$1"
  local pipeline_exit="$2"
  local subject_file="$3"
  local body_file="$4"
  local rfc822_file="$5"

  REPORT_PATH="$report_path" \
  PIPELINE_EXIT="$pipeline_exit" \
  SUBJECT_FILE="$subject_file" \
  BODY_FILE="$body_file" \
  RFC822_FILE="$rfc822_file" \
  EMAIL_TO="$EMAIL_TO" \
  EMAIL_FROM="$EMAIL_FROM" \
  EMAIL_SUBJECT_PREFIX="$EMAIL_SUBJECT_PREFIX" \
  python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def load_report(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


report_path = Path(os.environ["REPORT_PATH"])
pipeline_exit = int(os.environ["PIPELINE_EXIT"])
subject_file = Path(os.environ["SUBJECT_FILE"])
body_file = Path(os.environ["BODY_FILE"])
rfc822_file = Path(os.environ["RFC822_FILE"])
email_to = os.environ["EMAIL_TO"]
email_from = os.environ["EMAIL_FROM"]
prefix = os.environ["EMAIL_SUBJECT_PREFIX"]

report = load_report(report_path)
totals = report.get("totals") or {}
perfume_counts = report.get("perfume_insert_candidates_counts") or {}
safe_top_brands = report.get("safe_top_brands") or []
overall_status = report.get("status") or ("success" if pipeline_exit == 0 else "failure")
status_label = "success" if pipeline_exit == 0 and overall_status == "success" else "failure"
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
subject = f"{prefix} Pipeline {status_label} {today}"

top_brand_lines = []
for entry in safe_top_brands[:5]:
    brand = entry.get("candidate_brand") or "<unknown>"
    count = entry.get("count")
    top_brand_lines.append(f"- {brand}: {count}")
if not top_brand_lines:
    top_brand_lines.append("- none")

lines = [
    f"Status: {overall_status}",
    f"Pipeline exit code: {pipeline_exit}",
    f"Network: {report.get('network') or 'awin'}",
    f"Started at: {report.get('started_at') or '<unknown>'}",
    f"Finished at: {report.get('finished_at') or '<unknown>'}",
    f"Import run id: {report.get('latest_import_run_id') or '<unknown>'}",
    "",
    "Offer metrics:",
    f"- inserted: {totals.get('offers_inserted', 0)}",
    f"- updated: {totals.get('offers_updated', 0)}",
    f"- unchanged: {totals.get('offers_unchanged', 0)}",
    "",
    "Candidate metrics:",
    f"- created: {totals.get('candidates_created', 0)}",
    f"- updated: {totals.get('candidates_updated', 0)}",
    f"- unchanged: {totals.get('candidates_unchanged', 0)}",
    "",
    "Perfume staging sync:",
    f"- staging_inserted: {totals.get('staging_inserted', 0)}",
    f"- staging_updated: {totals.get('staging_updated', 0)}",
    f"- staging_ignored_manual_status: {totals.get('staging_ignored_manual_status', 0)}",
    f"- safe_new_candidates_count: {totals.get('safe_new_candidates_count', 0)}",
    "",
    "Refresh dry-run:",
    f"- candidates_loaded: {totals.get('refresh_candidates_loaded', 0)}",
    f"- candidates_would_update: {totals.get('refresh_candidates_would_update', 0)}",
    f"- candidates_without_match: {totals.get('refresh_candidates_without_match', 0)}",
    "",
    "perfume_insert_candidates counts:",
    f"- pending: {perfume_counts.get('pending', 0)}",
    f"- promoted: {perfume_counts.get('promoted', 0)}",
    f"- approved: {perfume_counts.get('approved', 0)}",
    "",
    "Top SAFE brands:",
    *top_brand_lines,
    "",
    f"Latest report: {report_path}",
]

body = "\n".join(lines) + "\n"
rfc822 = (
    f"Subject: {subject}\n"
    f"From: {email_from}\n"
    f"To: {email_to}\n"
    "Content-Type: text/plain; charset=utf-8\n"
    "\n"
    f"{body}"
)

subject_file.write_text(subject, encoding="utf-8")
body_file.write_text(body, encoding="utf-8")
rfc822_file.write_text(rfc822, encoding="utf-8")
PY
}

send_email_if_configured() {
  local pipeline_exit="$1"
  local report_path="$2"

  if ! is_true "$EMAIL_ENABLED"; then
    log "Host email report disabled."
    return 0
  fi

  if [ -z "$EMAIL_TO" ] || [ -z "$EMAIL_FROM" ]; then
    warn "Host email report enabled but recipient/sender is not fully configured."
    return 0
  fi

  local should_send=false
  if [ "$pipeline_exit" -eq 0 ]; then
    if is_true "$EMAIL_SEND_ON_SUCCESS"; then
      should_send=true
    fi
  else
    if is_true "$EMAIL_SEND_ON_FAILURE"; then
      should_send=true
    fi
  fi

  if [ "$should_send" != true ]; then
    log "Host email policy skipped delivery for this pipeline outcome."
    return 0
  fi

  if ! command -v "$EMAIL_COMMAND" >/dev/null 2>&1; then
    warn "Configured host email command is not available."
    return 0
  fi

  if [ "$EMAIL_COMMAND" != "sendmail" ] && [ "$EMAIL_COMMAND" != "mail" ]; then
    warn "Configured host email command is unsupported."
    return 0
  fi

  local subject_file body_file rfc822_file
  subject_file="$(mktemp)"
  body_file="$(mktemp)"
  rfc822_file="$(mktemp)"
  trap 'rm -f "$subject_file" "$body_file" "$rfc822_file"' RETURN

  write_email_files "$report_path" "$pipeline_exit" "$subject_file" "$body_file" "$rfc822_file"

  case "$EMAIL_COMMAND" in
    sendmail)
      if ! "$EMAIL_COMMAND" -t < "$rfc822_file"; then
        warn "Host email delivery failed."
        return 0
      fi
      ;;
    mail)
      mapfile -t recipients < <(printf '%s' "$EMAIL_TO" | tr ',' '\n' | sed 's/^ *//; s/ *$//' | awk 'NF')
      if [ "${#recipients[@]}" -eq 0 ]; then
        warn "Host email recipients are empty after parsing."
        return 0
      fi
      if ! "$EMAIL_COMMAND" -s "$(cat "$subject_file")" -r "$EMAIL_FROM" "${recipients[@]}" < "$body_file"; then
        warn "Host email delivery failed."
        return 0
      fi
      ;;
  esac

  log "Host email report sent."
}

main() {
  local -a pipeline_args
  mapfile -t pipeline_args < <(build_pipeline_args "$@")
  pipeline_args+=(--no-email-report)

  set +e
  "$DOCKER_BIN" run --rm \
    --network "$DOCKER_NETWORK" \
    --env-file "$WORKER_ENV_FILE" \
    -v "$DATA_DIR:/data" \
    "$WORKER_IMAGE" \
    run-affiliate-pipeline \
    "${pipeline_args[@]}"
  local pipeline_exit=$?
  set -e

  send_email_if_configured "$pipeline_exit" "$LATEST_REPORT_PATH"
  exit "$pipeline_exit"
}

main "$@"
