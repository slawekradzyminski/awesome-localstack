#!/usr/bin/env bash
# Contract check of the fault-injection lab and the tracing overlay.
#
# 1. `docker compose config --quiet` for every overlay combination (full and
#    lightweight with chaos, tracing and monitoring).
# 2. Starts lightweight + docker-compose.chaos.yml with the published images
#    through scripts/chaos, in its own Compose project and on its own host
#    ports, so it runs beside a developer's stack.
# 3. Runs every scenario and asserts an effect a student can observe with curl
#    (a warehouse 503, a slow or failing link, a database health check going
#    DOWN, the feed cursor holding still during a partition, a payment outbox
#    backlog), then heals and asserts recovery.
# 4. Adds and removes docker-compose.tracing.yml with scripts/tracing and
#    checks that Jaeger answers.
# 5. Tears the stack down with scripts/chaos down.
#
#   scripts/verify-chaos-overlay.sh
#
# Environment: COMPOSE_PROJECT_NAME (default chaos-verify), TOXIPROXY_PORT
# (18474), CHAOS_VERIFY_GATEWAY_PORT (18081), JAEGER_UI_PORT (26686),
# KEEP_RUNNING=true (no teardown). Needs curl and python3.
set -Eeuo pipefail

cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-chaos-verify}"
export TOXIPROXY_PORT="${TOXIPROXY_PORT:-18474}"
export JAEGER_UI_PORT="${JAEGER_UI_PORT:-26686}"
GATEWAY_PORT="${CHAOS_VERIFY_GATEWAY_PORT:-18081}"
B="http://127.0.0.1:$GATEWAY_PORT"
RUN="cv$(date +%H%M%S)$RANDOM"

work="$(mktemp -d)"
# Own host ports; no docs image build (its local tag is shared with other stacks).
cat > "$work/verify-ports.yml" <<EOF
services:
  gateway:
    ports: !override
      - "127.0.0.1:$GATEWAY_PORT:80"
  ollama-mock:
    ports: !reset []
  docs:
    profiles: ["verify-skip"]
EOF
export CHAOS_EXTRA_FILES="$work/verify-ports.yml"
compose=(docker compose -f lightweight-docker-compose.yml -f docker-compose.chaos.yml -f "$work/verify-ports.yml")

PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); printf '  PASS %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  FAIL %s -- %s\n' "$1" "${2:-}"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected '$3', got '$2'"; fi; }
section() { printf '\n== %s\n' "$1"; }
chaos() { scripts/chaos "$@" >/dev/null; }

cleanup() {
  result=$?
  if [[ $result -ne 0 || $FAIL -ne 0 ]]; then
    "${compose[@]}" ps --all || true
    "${compose[@]}" logs --no-color --tail=60 toxiproxy warehouse-service payment-service notification-service || true
  fi
  if [[ "${KEEP_RUNNING:-false}" != "true" ]]; then
    docker compose -p "$COMPOSE_PROJECT_NAME" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$work"
  exit "$result"
}
trap cleanup EXIT

json() {  # python expression over `d` (parsed stdin)
  python3 -c "import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = None
print($1)"
}
J='Content-Type: application/json'
api() {  # METHOD PATH TOKEN [BODY] [extra curl args...] -> $BODY $CODE $TIME
  local out; out="$(mktemp)"
  local args=(-s -o "$out" -w '%{http_code} %{time_total}' -X "$1" "$B$2" -H "$J" -H "X-Request-Id: $RUN-$RANDOM" --max-time 60)
  [ -n "$3" ] && args+=(-H "Authorization: Bearer $3")
  [ -n "${4:-}" ] && args+=(-d "$4")
  [ $# -gt 4 ] && args+=("${@:5}")
  local result; result="$(curl "${args[@]}" || echo "000 0")"
  CODE="${result% *}"; TIME="${result#* }"; BODY="$(cat "$out")"; rm -f "$out"
}
signin() { api POST /api/v1/users/signin "" "{\"username\":\"$1\",\"password\":\"$2\"}"; echo "$BODY" | json 'd["token"]'; }
inside() { "${compose[@]}" exec -T gateway curl "$@"; }  # curl from inside the network
sql() { "${compose[@]}" exec -T postgres psql -U postgres -d testdb -Atc "$1"; }
health() {  # service:port -> HTTP status of /actuator/health
  inside -s -o /dev/null -w '%{http_code}' --max-time "${2:-45}" "http://$1/actuator/health" || true
}
wait_for() {  # seconds command expected
  local got=""; for _ in $(seq 1 "$1"); do got="$(eval "$2" 2>/dev/null || true)"; [ "$got" = "$3" ] && break; sleep 1; done; echo "$got"
}
new_order() {  # token -> order id in $OID
  api GET "/api/v1/products/search?inStock=true&sort=price_asc&size=1" "$1"
  local pid; pid="$(echo "$BODY" | json 'd["content"][0]["id"]')"
  api POST /api/v1/cart/items "$1" "{\"productId\":$pid,\"quantity\":1}"
  api POST /api/v1/orders "$1" '{"street":"Marszalkowska 1","city":"Warszawa","state":"M","zipCode":"00-001","country":"Poland"}'
  OID="$(echo "$BODY" | json 'd["id"]')"
}
pay() {  # token orderId card -> payment id in $PID, status in $PSTATUS
  api POST /api/v1/payments "$1" "{\"orderId\":$2,\"card\":{\"number\":\"$3\",\"expiryMonth\":12,\"expiryYear\":2031,\"cvc\":\"123\",\"holderName\":\"Chaos Tester\"}}" \
    -H "Idempotency-Key: $RUN-$2-$RANDOM"
  [ "$CODE" = 201 ] || bad "payment for order $2" "$CODE $BODY"
  PID="$(echo "$BODY" | json 'd["id"]')"; PSTATUS="$(echo "$BODY" | json 'd["status"]')"
}
order_status() { api GET "/api/v1/orders/$2" "$1"; echo "$BODY" | json 'd["status"]'; }

section "Compose configurations"
for base in docker-compose.yml lightweight-docker-compose.yml; do
  for overlays in "chaos" "tracing" "chaos tracing" "chaos monitoring" "tracing monitoring" "chaos tracing monitoring"; do
    files=(-f "$base")
    for overlay in $overlays; do files+=(-f "docker-compose.$overlay.yml"); done
    if docker compose "${files[@]}" config --quiet; then ok "$base + $overlays"; else bad "$base + $overlays" "config failed"; fi
  done
done
url="$(docker compose -f lightweight-docker-compose.yml -f docker-compose.chaos.yml config --format json \
  | json 'd["services"]["notification-service"]["environment"]["BACKEND_BASE_URL"]')"
check "notification-service goes through toxiproxy:34001" "$url" "http://toxiproxy:34001"

section "Start lightweight + chaos ($COMPOSE_PROJECT_NAME, gateway $B, Toxiproxy 127.0.0.1:$TOXIPROXY_PORT)"
"${compose[@]}" pull --ignore-buildable --quiet
scripts/chaos up lightweight
status="$(scripts/chaos status)"
check "status lists the 7 proxies" "$(printf '%s\n' "$status" | grep -cE '^[a-z]+-to-(backend|postgres) ')" 7
printf '%s\n' "$status" | grep -q 'No faults active' && ok "no faults after start" || bad "no faults after start" "$status"
for svc in backend warehouse-service payment-service notification-service; do
  env="$(docker inspect "$("${compose[@]}" ps -q "$svc")" --format '{{range .Config.Env}}{{println .}}{{end}}')"
  printf '%s\n' "$env" | grep -qE '^(SPRING_DATASOURCE_URL=jdbc:postgresql://toxiproxy:|BACKEND_BASE_URL=http://toxiproxy:)' \
    && ok "$svc is wired through toxiproxy" || bad "$svc wiring" "$env"
done

A="$(signin admin 'LocalDemoAdmin123!')"; W="$(signin warehouse warehouse)"
u="cv$RANDOM$RANDOM"
api POST /api/v1/users/signup "" "{\"username\":\"$u\",\"email\":\"$u@example.com\",\"password\":\"Chaos12345!\",\"firstName\":\"Chaos\",\"lastName\":\"Tester\",\"roles\":[\"ROLE_CLIENT\"]}"
T="$(signin "$u" 'Chaos12345!')"
[ -n "$A" ] && [ -n "$W" ] && [ "$T" != None ] && ok "admin, warehouse and a fresh client signed in" || { bad "sign-in" "$BODY"; exit 1; }
api GET /api/v1/warehouse/queue "$W"; check "warehouse queue answers (JWKS cached)" "$CODE" 200

section "backend-down warehouse"
chaos backend-down warehouse
api GET /api/v1/warehouse/queue "$W"
check "warehouse queue -> 503" "$CODE" 503
check "503 says Backend unavailable" "$(echo "$BODY" | json 'd and d.get("message")')" "Backend unavailable"
new_order "$T"; O1="$OID"
check "the backend itself still answers (order created through the direct route)" "$CODE" 201
scripts/chaos status | grep -E '^warehouse-to-backend .*DISABLED' >/dev/null && ok "status shows warehouse-to-backend DISABLED" || bad "status DISABLED"
chaos heal
api GET /api/v1/warehouse/queue "$W"; check "after heal: warehouse queue -> 200" "$CODE" 200

section "backend-slow 2000 warehouse"
chaos backend-slow 2000 warehouse
api GET /api/v1/warehouse/queue "$W"
check "slow queue still 200" "$CODE" 200
python3 -c "import sys; sys.exit(0 if float('$TIME') >= 2.0 else 1)" && ok "queue took ${TIME}s (>= 2 s)" || bad "slow queue" "took ${TIME}s"
chaos heal
api GET /api/v1/warehouse/queue "$W"
python3 -c "import sys; sys.exit(0 if float('$TIME') < 2.0 else 1)" && ok "after heal: queue took ${TIME}s" || bad "healed queue" "took ${TIME}s"

section "backend-flaky 100 warehouse (new TCP connection per request)"
chaos backend-flaky 100 warehouse
failed=0
for _ in 1 2 3 4 5 6 7 8; do
  code="$(inside -s -o /dev/null -w '%{http_code}' --max-time 7 http://toxiproxy:14001/actuator/health || true)"
  [ "$code" = 200 ] || failed=$((failed + 1))
done
[ "$failed" -ge 3 ] && ok "$failed of 8 requests through warehouse-to-backend failed" || bad "flaky" "only $failed of 8 failed"
chaos heal
check "after heal: link answers" "$(inside -s -o /dev/null -w '%{http_code}' --max-time 7 http://toxiproxy:14001/actuator/health || true)" 200

section "bandwidth 8 warehouse"
chaos bandwidth 8 warehouse
speed="$(inside -s -o /dev/null -w '%{speed_download}' --max-time 4 http://toxiproxy:14001/v3/api-docs || true)"
python3 -c "import sys; sys.exit(0 if 0 < float('${speed:-0}') <= 12000 else 1)" && ok "download through the link at ${speed} B/s" || bad "bandwidth" "speed ${speed} B/s"
chaos heal
speed="$(inside -s -o /dev/null -w '%{speed_download}' --max-time 10 http://toxiproxy:14001/v3/api-docs || true)"
python3 -c "import sys; sys.exit(0 if float('${speed:-0}') > 100000 else 1)" && ok "after heal: ${speed} B/s" || bad "bandwidth heal" "speed ${speed} B/s"

section "postgres-down warehouse"
chaos postgres-down warehouse
check "warehouse health -> 503 (database DOWN)" "$(health warehouse-service:4003)" 503
check "payment health unaffected" "$(health payment-service:4004 10)" 200
chaos heal
check "after heal: warehouse health -> 200" "$(wait_for 90 'health warehouse-service:4003 5' 200)" 200

section "postgres-stall warehouse"
chaos postgres-stall warehouse
code="$(health warehouse-service:4003 50)"
[ "$code" != 200 ] && ok "warehouse health not 200 while its database stalls ($code)" || bad "postgres-stall" "health $code"
chaos heal
check "after heal: warehouse health -> 200" "$(wait_for 120 'health warehouse-service:4003 5' 200)" 200

section "partition-payment"
chaos partition-payment
check "payment health -> 503" "$(health payment-service:4004)" 503
api GET /api/v1/warehouse/queue "$W"; check "warehouse unaffected" "$CODE" 200
chaos heal
check "after heal: payment health -> 200" "$(wait_for 120 'health payment-service:4004 5' 200)" 200

section "partition-warehouse: the feed consumer resumes from its cursor"
pay "$T" "$O1" 4242424242424242
check "card payment captured" "$PSTATUS" CAPTURED
check "order PAID" "$(wait_for 30 "order_status $T $O1" PAID)" PAID
api POST /api/v1/warehouse/shipments "$W" "{\"orderId\":$O1}"; check "shipment released" "$CODE" 201
SID="$(echo "$BODY" | json 'd["id"]')"
cursor_sql="select last_sequence from warehouse.event_cursors where consumer = 'warehouse-service'"
before="$(sql "$cursor_sql")"
chaos partition-warehouse
api POST "/api/v1/orders/$O1/cancel" "$T"; check "customer cancels the order (backend direct route)" "$CODE" 200
sleep 15
check "shipment still AWAITING_PICK during the partition" "$(sql "select status from warehouse.shipments where id = $SID")" AWAITING_PICK
check "cursor did not move during the partition" "$(sql "$cursor_sql")" "$before"
chaos heal
check "after heal: shipment CANCELLED by the feed" \
  "$(wait_for 120 "sql \"select status from warehouse.shipments where id = $SID\"" CANCELLED)" CANCELLED
after="$(sql "$cursor_sql")"
[ "${after:-0}" -gt "${before:-0}" ] && ok "cursor moved $before -> $after" || bad "cursor" "$before -> $after"
check "card refunded by payment-service" \
  "$(wait_for 60 "api GET /api/v1/payments/$PID $T; echo \$BODY | json 'd[\"status\"]'" REFUNDED)" REFUNDED

section "backend-down payment: payment outbox backlog grows and drains"
new_order "$T"; O2="$OID"
pay "$T" "$O2" 4000000000000077
check "async card -> PROCESSING" "$PSTATUS" PROCESSING
chaos backend-down payment
pending_sql="select count(*) from payment.payment_outbox where sent_at is null"
pending="$(wait_for 40 "[ \"\$(sql \"$pending_sql\")\" -gt 0 ] && echo yes" yes)"
check "payment result waits in payment_outbox" "$pending" yes
check "order still PENDING" "$(order_status "$T" "$O2")" PENDING
chaos heal
check "after heal: order PAID" "$(wait_for 90 "order_status $T $O2" PAID)" PAID
check "after heal: payment_outbox drained" "$(wait_for 30 "sql \"$pending_sql\"" 0)" 0

section "backend-down payment + cancel: late payment result -> 409 -> VOIDED"
new_order "$T"; O3="$OID"
pay "$T" "$O3" 4000000000000077; P3="$PID"
check "async card -> PROCESSING" "$PSTATUS" PROCESSING
chaos backend-down payment
check "payment result waits in payment_outbox" \
  "$(wait_for 40 "sql \"select count(*) from payment.payment_outbox where order_id = $O3 and sent_at is null\"" 1)" 1
api POST "/api/v1/orders/$O3/cancel" "$T"; check "customer cancels the order meanwhile" "$CODE" 200
chaos heal
check "after heal: payment VOIDED" \
  "$(wait_for 90 "api GET /api/v1/payments/$P3 $T; echo \$BODY | json 'd[\"status\"]'" VOIDED)" VOIDED
check "outbox recorded the 409" "$(sql "select last_error from payment.payment_outbox where order_id = $O3")" "409 Order is not payable"
check "order stays CANCELLED" "$(order_status "$T" "$O3")" CANCELLED

section "Tracing overlay on top of the lab"
scripts/tracing up lightweight >/dev/null
check "Jaeger UI answers" "$(wait_for 60 "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$JAEGER_UI_PORT/" 200)" 200
check "Jaeger query API answers" "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$JAEGER_UI_PORT/api/v3/services")" 200
env="$(docker inspect "$("${compose[@]}" ps -q backend)" --format '{{range .Config.Env}}{{println .}}{{end}}')"
printf '%s\n' "$env" | grep -qx 'TRACING_ENABLED=true' && printf '%s\n' "$env" | grep -q '^SPRING_DATASOURCE_URL=jdbc:postgresql://toxiproxy:' \
  && ok "backend has tracing on and still goes through toxiproxy" || bad "backend env" "$env"
check "backend healthy again" "$(wait_for 180 "docker inspect --format '{{.State.Health.Status}}' \$(${compose[*]} ps -q backend)" healthy)" healthy
scripts/tracing down lightweight >/dev/null
check "Jaeger removed" "$(docker ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" --filter label=com.docker.compose.service=jaeger | wc -l | tr -d ' ')" 0
check "lab still running" "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$TOXIPROXY_PORT/version")" 200

section "Tear down"
if [[ "${KEEP_RUNNING:-false}" != "true" ]]; then
  scripts/chaos down >/dev/null 2>&1
  check "scripts/chaos down removed the stack" \
    "$(docker ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" | wc -l | tr -d ' ')" 0
fi

printf '\nResult: %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
