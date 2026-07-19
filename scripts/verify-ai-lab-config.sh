#!/usr/bin/env bash

set -euo pipefail

stack_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${stack_dir}"

full_local_config="$(docker compose -f docker-compose.yml -f docker-compose.ai-lab-local.yml config)"
lightweight_build_config="$(docker compose -f lightweight-docker-compose.yml -f docker-compose.ai-lab-build.yml config)"
server_config="$(docker compose -f docker-compose.server.yml config)"
e2e_config="$(docker compose -f docker-compose.ai-lab-e2e.yml config)"

grep -F 'VITE_AI_LIVE_RUNTIME_ENABLED: "true"' <<<"${full_local_config}"

for guided_config in "${lightweight_build_config}" "${server_config}" "${e2e_config}"; do
  if grep -Fq 'VITE_AI_LIVE_RUNTIME_ENABLED' <<<"${guided_config}"; then
    echo "Live AI runtime must be opt-in only in the full-local override." >&2
    exit 1
  fi
done

echo "AI Learning Lab profile capability checks passed."
