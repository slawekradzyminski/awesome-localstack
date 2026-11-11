#!/usr/bin/env bash
# Start a local base profile with docker-compose.monitoring.yml, then require
# every provisioned Grafana dashboard and every Prometheus target to be UP.
#
#   scripts/verify-monitoring-overlay.sh [base-compose-file] [extra -f files...]
#
# Environment: GRAFANA_PORT, PROMETHEUS_PORT (also passed to Compose),
# COMPOSE_PROJECT_NAME (run beside another stack), KEEP_RUNNING=true (no teardown).
set -Eeuo pipefail

cd "$(dirname "$0")/.."
base="${1:-lightweight-docker-compose.yml}"
shift || true
compose=(docker compose -f "$base" -f docker-compose.monitoring.yml)
for extra in "$@"; do
  compose+=(-f "$extra")
done
grafana="http://127.0.0.1:${GRAFANA_PORT:-3000}"
prometheus="http://127.0.0.1:${PROMETHEUS_PORT:-9090}"

cleanup() {
  result=$?
  if [[ $result -ne 0 ]]; then
    "${compose[@]}" ps --all || true
    "${compose[@]}" logs --no-color --tail=100 prometheus grafana cadvisor node-exporter || true
  fi
  if [[ "${KEEP_RUNNING:-false}" != "true" ]]; then
    "${compose[@]}" down --volumes --remove-orphans
  fi
  exit "$result"
}
trap cleanup EXIT

"${compose[@]}" config --quiet
"${compose[@]}" pull --ignore-buildable --quiet
# No --wait: some Compose releases treat the keycloak-init one-shot's exit as a
# failure. The polling below waits for what this check needs.
"${compose[@]}" up -d

for _ in $(seq 1 60); do
  curl --fail --silent --output /dev/null "$grafana/api/health" && break
  sleep 3
done
for uid in XKhgaUpik spring_boot_21 http awesome-container-resources; do
  title="$(curl --fail --silent --show-error --user admin:grafana "$grafana/api/dashboards/uid/$uid" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["dashboard"]["title"])')"
  echo "Grafana dashboard $uid: $title"
done
curl --fail --silent --show-error --user admin:grafana "$grafana/api/datasources" \
  | python3 -c 'import json, sys; names = {d["name"] for d in json.load(sys.stdin)}; assert {"Prometheus", "InfluxDB"} <= names, names'

# Consumer exists only in the full profile; DNS discovery gives it no target elsewhere.
expected="spring_backend_micrometer spring_warehouse_micrometer spring_payment_micrometer cadvisor node prometheus"
if "${compose[@]}" config --services | grep -qx consumer; then
  expected="$expected spring_consumer_micrometer"
fi
for _ in $(seq 1 36); do
  if curl --fail --silent "$prometheus/api/v1/targets" | EXPECTED="$expected" python3 -c '
import json, os, sys
targets = json.load(sys.stdin)["data"]["activeTargets"]
up = {t["labels"]["job"] for t in targets if t["health"] == "up"}
down = sorted(t["labels"]["job"] for t in targets if t["health"] != "up")
missing = sorted(set(os.environ["EXPECTED"].split()) - up)
print(f"Prometheus targets up={sorted(up)} down={down} missing={missing}")
sys.exit(0 if not down and not missing else 1)
'; then
    exit 0
  fi
  sleep 5
done
echo "Prometheus targets did not all come UP" >&2
exit 1
