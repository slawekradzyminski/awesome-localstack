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

required_vars=(SSH_HOST SSH_PORT SSH_USER SSH_PASSWORD)
for name in "${required_vars[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required variable: ${name}" >&2
    exit 1
  fi
done

if ! command -v expect >/dev/null 2>&1; then
  echo "expect is required for password-based SSH deployment" >&2
  exit 1
fi

create_archive() {
  local archive_path="$1"
  tar -C "${ROOT_DIR}" -czf "${archive_path}" \
    docker-compose.server.yml \
    install-docker-ubuntu.sh \
    images \
    nginx
}

run_expect() {
  local script="$1"
  expect <<EOF
set timeout -1
${script}
EOF
}

TMP_ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/awesome-localstack.XXXXXX.tgz")"
trap 'rm -f "${TMP_ARCHIVE}"' EXIT

create_archive "${TMP_ARCHIVE}"

run_expect "
spawn scp -P ${SSH_PORT} -o StrictHostKeyChecking=accept-new ${TMP_ARCHIVE} ${SSH_USER}@${SSH_HOST}:/tmp/awesome-localstack.tgz
expect {
  -re \".*assword:.*\" { send -- \"${SSH_PASSWORD}\r\"; exp_continue }
  eof
}
"

run_expect "
set remote_cmd [list bash -lc {set -euo pipefail; mkdir -p ${REMOTE_APP_DIR}; tar -xzf /tmp/awesome-localstack.tgz -C ${REMOTE_APP_DIR}; cd ${REMOTE_APP_DIR}; if ! command -v docker >/dev/null 2>&1; then bash install-docker-ubuntu.sh; fi; docker compose -f docker-compose.server.yml pull; docker compose -f docker-compose.server.yml up -d; docker compose -f docker-compose.server.yml up -d --force-recreate gateway frontend backend nginx-static}]
spawn ssh -tt -p ${SSH_PORT} -o StrictHostKeyChecking=accept-new -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no ${SSH_USER}@${SSH_HOST} {*}\$remote_cmd
expect {
  -re \".*assword:.*\" { send -- \"${SSH_PASSWORD}\r\"; exp_continue }
  eof
}
"
