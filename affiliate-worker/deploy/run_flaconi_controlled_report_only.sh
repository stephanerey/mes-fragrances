#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/eva/mes-fragrances}"
DOCKER_BIN="${DOCKER_BIN:-/usr/bin/docker}"
WORKER_IMAGE="${WORKER_IMAGE:-mes-fragrances-affiliate-worker:flaconi-controlled-current}"
WORKER_ENV_FILE="${WORKER_ENV_FILE:-$ROOT_DIR/affiliate-worker/.env}"
DATA_DIR="${DATA_DIR:-$ROOT_DIR/affiliate-worker-data}"
REPORT_ROOT="${REPORT_ROOT:-$DATA_DIR/reports}"
DOCKER_NETWORK="${AFFILIATE_DOCKER_NETWORK:-mes-fragrances_cis_default}"
ADVERTISER_ID="${FLACONI_NETWORK_ADVERTISER_ID:-87361}"
FEED_ID="${FLACONI_NETWORK_FEED_ID:-97463}"
RUN_TS="${RUN_TS:-$(date -u +%Y%m%d_%H%M%S)}"
REPORT_PREFIX="${REPORT_PREFIX:-flaconi_controlled_report_only}"
REPORT_DIR_NAME="${REPORT_DIR_NAME:-${REPORT_PREFIX}_${RUN_TS}}"
HOST_REPORT_DIR="${REPORT_ROOT}/${REPORT_DIR_NAME}"
CONTAINER_REPORT_DIR="/data/reports/${REPORT_DIR_NAME}"
LATEST_LINK="${LATEST_LINK:-${REPORT_ROOT}/${REPORT_PREFIX}_latest}"

mkdir -p "${REPORT_ROOT}"

"${DOCKER_BIN}" run --rm \
  --network "${DOCKER_NETWORK}" \
  --env-file "${WORKER_ENV_FILE}" \
  -v "${DATA_DIR}:/data" \
  "${WORKER_IMAGE}" \
  flaconi-grouped-dry-run \
  --advertiser "${ADVERTISER_ID}" \
  --feed-id "${FEED_ID}" \
  --report-dir "${CONTAINER_REPORT_DIR}" \
  "$@"

if [ -d "${HOST_REPORT_DIR}" ]; then
  ln -sfn "${HOST_REPORT_DIR}" "${LATEST_LINK}"
fi

printf 'host_report_dir=%s\n' "${HOST_REPORT_DIR}"
printf 'latest_link=%s\n' "${LATEST_LINK}"
