#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/opt/awesome-localstack}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo ".env not found at ${ENV_FILE}" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

required_vars=(SSH_HOST SSH_PORT SSH_USER SSH_KEY_PATH)
for name in "${required_vars[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required variable: ${name}" >&2
    exit 1
  fi
done

if [[ ! -f "${SSH_KEY_PATH}" ]]; then
  echo "SSH key not found at ${SSH_KEY_PATH}" >&2
  exit 1
fi

create_archive() {
  local archive_path="$1"
  local runtime_env_path="${ROOT_DIR}/.env.runtime"
  local grafana_admin_password="${GRAFANA_ADMIN_PASSWORD:-${GF_SECURITY_ADMIN_PASSWORD:-}}"

  {
    if [[ -n "${grafana_admin_password}" ]]; then
      printf 'GF_SECURITY_ADMIN_PASSWORD=%s\n' "${grafana_admin_password}"
    fi
  } > "${runtime_env_path}"

  tar -C "${ROOT_DIR}" -czf "${archive_path}" \
    docker-compose.server.yml \
    .env.runtime \
    grafana \
    install-docker-ubuntu.sh \
    images \
    nginx \
    prometheus
}

TMP_ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/awesome-localstack.XXXXXX.tgz")"
TMP_RUNTIME_ENV="${ROOT_DIR}/.env.runtime"
trap 'rm -f "${TMP_ARCHIVE}" "${TMP_RUNTIME_ENV}"' EXIT

create_archive "${TMP_ARCHIVE}"

scp -P "${SSH_PORT}" -i "${SSH_KEY_PATH}" -o StrictHostKeyChecking=accept-new \
  "${TMP_ARCHIVE}" "${SSH_USER}@${SSH_HOST}:/tmp/awesome-localstack.tgz"

ssh -tt -p "${SSH_PORT}" -i "${SSH_KEY_PATH}" -o StrictHostKeyChecking=accept-new \
  "${SSH_USER}@${SSH_HOST}" \
  "bash -lc 'set -euo pipefail; \
    mkdir -p \"${REMOTE_APP_DIR}\"; \
    tar -xzf /tmp/awesome-localstack.tgz -C \"${REMOTE_APP_DIR}\"; \
    cd \"${REMOTE_APP_DIR}\"; \
    if ! command -v docker >/dev/null 2>&1; then bash install-docker-ubuntu.sh; fi; \
    docker compose -f docker-compose.server.yml down --remove-orphans; \
    docker compose -f docker-compose.server.yml pull; \
    docker compose -f docker-compose.server.yml up -d --force-recreate --remove-orphans'"
