#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
stack_dir="$(cd "${script_dir}/.." && pwd)"
lab_dir="${AI_LAB_BUILD_CONTEXT:-${stack_dir}/../ai-learning-lab}"
e2e_port="${AI_LAB_E2E_PORT:-18081}"
compose_file="${stack_dir}/docker-compose.ai-lab-e2e.yml"

cleanup() {
  docker compose -f "${compose_file}" down --volumes --remove-orphans
}

trap cleanup EXIT

docker compose -f "${compose_file}" up -d --build --wait
curl --fail --silent --show-error --retry 30 --retry-connrefused --retry-delay 1 --max-time 45 "http://127.0.0.1:${e2e_port}/learn/" >/dev/null

(
  cd "${lab_dir}"
  E2E_BASE_URL="http://127.0.0.1:${e2e_port}" PLAYWRIGHT_HTML_OPEN=never npx playwright test e2e/gateway-integration.spec.ts --reporter=list
)
