#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/eva/mes-fragrances}"
DOCKER_BIN="${DOCKER_BIN:-/usr/bin/docker}"
WORKER_IMAGE="${WORKER_IMAGE:-mes-fragrances-affiliate-worker}"
WORKER_ENV_FILE="${WORKER_ENV_FILE:-$ROOT_DIR/affiliate-worker/.env}"
DATA_DIR="${DATA_DIR:-$ROOT_DIR/affiliate-worker-data}"
REPORT_ROOT="${REPORT_ROOT:-$DATA_DIR/reports}"
DOCKER_NETWORK="${AFFILIATE_DOCKER_NETWORK:-mes-fragrances_cis_default}"

DIGEST_EMAIL_ENABLED="${AFFILIATE_HOST_DIGEST_EMAIL_ENABLED:-false}"
DIGEST_EMAIL_TO="${AFFILIATE_HOST_DIGEST_EMAIL_TO:-}"
DIGEST_EMAIL_FROM="${AFFILIATE_HOST_DIGEST_EMAIL_FROM:-}"
DIGEST_EMAIL_SUBJECT_PREFIX="${AFFILIATE_HOST_DIGEST_EMAIL_SUBJECT_PREFIX:-[Awin Digest]}"
DIGEST_EMAIL_COMMAND="${AFFILIATE_HOST_DIGEST_EMAIL_COMMAND:-sendmail}"
DIGEST_SINCE_DAYS="${AFFILIATE_HOST_DIGEST_SINCE_DAYS:-7}"
DIGEST_LOCALE="${AFFILIATE_HOST_DIGEST_LOCALE:-fr}"

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

send_digest_email_if_configured() {
  local subject="$1"
  local markdown_path="$2"

  if ! is_true "$DIGEST_EMAIL_ENABLED"; then
    log "Host digest email disabled."
    return 0
  fi

  if [ -z "$DIGEST_EMAIL_TO" ] || [ -z "$DIGEST_EMAIL_FROM" ]; then
    warn "Host digest email enabled but recipient/sender is not fully configured."
    return 0
  fi

  if [ ! -f "$markdown_path" ]; then
    warn "Digest markdown report not found: $markdown_path"
    return 0
  fi

  if ! command -v "$DIGEST_EMAIL_COMMAND" >/dev/null 2>&1; then
    warn "Configured host digest email command is not available."
    return 0
  fi

  if [ "$DIGEST_EMAIL_COMMAND" != "sendmail" ] && [ "$DIGEST_EMAIL_COMMAND" != "mail" ]; then
    warn "Configured host digest email command is unsupported."
    return 0
  fi

  local subject_file body_file rfc822_file
  subject_file="$(mktemp)"
  body_file="$(mktemp)"
  rfc822_file="$(mktemp)"
  trap 'rm -f "$subject_file" "$body_file" "$rfc822_file"' RETURN

  printf '%s\n' "$subject" > "$subject_file"
  cat "$markdown_path" > "$body_file"
  {
    printf 'Subject: %s\n' "$subject"
    printf 'From: %s\n' "$DIGEST_EMAIL_FROM"
    printf 'To: %s\n' "$DIGEST_EMAIL_TO"
    printf 'Content-Type: text/plain; charset=utf-8\n\n'
    cat "$body_file"
  } > "$rfc822_file"

  case "$DIGEST_EMAIL_COMMAND" in
    sendmail)
      if ! "$DIGEST_EMAIL_COMMAND" -t < "$rfc822_file"; then
        warn "Host digest email delivery failed."
        return 0
      fi
      ;;
    mail)
      mapfile -t recipients < <(printf '%s' "$DIGEST_EMAIL_TO" | tr ',' '\n' | sed 's/^ *//; s/ *$//' | awk 'NF')
      if [ "${#recipients[@]}" -eq 0 ]; then
        warn "Host digest email recipients are empty after parsing."
        return 0
      fi
      if ! "$DIGEST_EMAIL_COMMAND" -s "$(cat "$subject_file")" -r "$DIGEST_EMAIL_FROM" "${recipients[@]}" < "$body_file"; then
        warn "Host digest email delivery failed."
        return 0
      fi
      ;;
  esac

  log "Host digest email sent."
}

main() {
  local run_ts digest_dir_host digest_dir_container digest_subject digest_output digest_exit
  run_ts="$(date +%Y%m%d_%H%M%S)"
  digest_dir_host="$REPORT_ROOT/affiliate_digest_weekly_${run_ts}"
  digest_dir_container="/data/reports/affiliate_digest_weekly_${run_ts}"
  digest_subject="${DIGEST_EMAIL_SUBJECT_PREFIX} Digest hebdomadaire"
  mkdir -p "$digest_dir_host"

  set +e
  digest_output="$(
    "$DOCKER_BIN" run --rm \
      --network "$DOCKER_NETWORK" \
      --env-file "$WORKER_ENV_FILE" \
      -v "$DATA_DIR:/data" \
      "$WORKER_IMAGE" \
      digest-reports \
      --reports-root /data/reports \
      --since-days "$DIGEST_SINCE_DAYS" \
      --locale "$DIGEST_LOCALE" \
      --output-dir "$digest_dir_container" \
      --email-subject "$digest_subject" \
      --dry-run \
      "$@" \
      2>&1
  )"
  digest_exit=$?
  set -e

  printf '%s\n' "$digest_output"
  if [ "$digest_exit" -ne 0 ]; then
    exit "$digest_exit"
  fi

  local markdown_path_container markdown_path_host subject_from_digest
  markdown_path_container="$(printf '%s\n' "$digest_output" | sed -n 's/^markdown_report_path=//p' | tail -n 1)"
  subject_from_digest="$(printf '%s\n' "$digest_output" | sed -n 's/^email_subject=//p' | tail -n 1)"
  if [ -n "$subject_from_digest" ]; then
    digest_subject="$subject_from_digest"
  fi
  if [ -z "$markdown_path_container" ]; then
    warn "Digest command did not return markdown_report_path."
    return 0
  fi
  markdown_path_host="$DATA_DIR${markdown_path_container#/data}"

  send_digest_email_if_configured "$digest_subject" "$markdown_path_host"
}

main "$@"
