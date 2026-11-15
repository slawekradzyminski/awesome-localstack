#!/usr/bin/env bash
# Contract check of the broker transport (docs/EVENT_BROKER_CONTRACT.md).
#
# 1. `docker compose config --quiet` for the broker overlay combinations and the
#    transport each profile runs (full: broker, lightweight: feed, lightweight +
#    docker-compose.broker.yml: broker; the chaos overlay re-points every broker
#    client at Toxiproxy).
# 2. Starts lightweight + docker-compose.broker.yml + docker-compose.chaos.yml with
#    the published images through `scripts/chaos up lightweight broker`, in its
#    own Compose project and on its own host ports.
# 3. Checks what a student observes: the declared queues with one consumer each,
#    a cancellation reaching warehouse-service (stock restore) and
#    payment-service (card refund) through Artemis with the feed cursors standing
#    still, a poison message dead-lettered after five deliveries and redriven, a
#    stopped consumer's backlog waiting in its queue and draining, the backend's
#    relay backlog growing while it cannot reach the broker (checkout keeps
#    working) and draining after heal, and a consumer that loses the broker
#    reconnecting.
# 4. Tears the stack down.
#
#   scripts/verify-event-broker.sh
#
# Environment: COMPOSE_PROJECT_NAME (default broker-verify), TOXIPROXY_PORT
# (19474), BROKER_VERIFY_GATEWAY_PORT (19081), ARTEMIS_CONSOLE_PORT (19161),
# KEEP_RUNNING=true (no teardown), BROKER_VERIFY_EXTRA_FILES (more -f files, e.g.
# an override with candidate images; then also BROKER_VERIFY_PULL=false).
# Needs curl and python3.
set -Eeuo pipefail

cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-broker-verify}"
export TOXIPROXY_PORT="${TOXIPROXY_PORT:-19474}"
export ARTEMIS_CONSOLE_PORT="${ARTEMIS_CONSOLE_PORT:-19161}"
GATEWAY_PORT="${BROKER_VERIFY_GATEWAY_PORT:-19081}"
B="http://127.0.0.1:$GATEWAY_PORT"
RUN="bv$(date +%H%M%S)$RANDOM"

work="$(mktemp -d)"
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
export CHAOS_EXTRA_FILES="$work/verify-ports.yml ${BROKER_VERIFY_EXTRA_FILES:-}"
compose=(docker compose -f lightweight-docker-compose.yml -f docker-compose.broker.yml -f docker-compose.chaos.yml
         -f "$work/verify-ports.yml")
for extra in ${BROKER_VERIFY_EXTRA_FILES:-}; do compose+=(-f "$extra"); done

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
    "${compose[@]}" logs --no-color --tail=80 activemq backend warehouse-service payment-service notification-service || true
  fi
  if [[ "${KEEP_RUNNING:-false}" != "true" ]]; then
    docker compose -p "$COMPOSE_PROJECT_NAME" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$work"
  printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
  [[ $FAIL -eq 0 ]] || result=1
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
inside() { "${compose[@]}" exec -T gateway curl "$@"; }
sql() { "${compose[@]}" exec -T postgres psql -U postgres -d testdb -Atc "$1"; }
wait_for() {  # seconds command expected
  local got=""; for _ in $(seq 1 "$1"); do got="$(eval "$2" 2>/dev/null || true)"; [ "$got" = "$3" ] && break; sleep 1; done; echo "$got"
}
ADDR='{"street":"Marszalkowska 1","city":"Warszawa","state":"M","zipCode":"00-001","country":"Poland"}'
new_order() {  # token -> order id in $OID, product in $SP
  api GET "/api/v1/products/search?inStock=true&sort=price_asc&size=1" "$1"
  SP="$(echo "$BODY" | json 'd["content"][0]["id"]')"
  api DELETE /api/v1/cart "$1"
  api POST /api/v1/cart/items "$1" "{\"productId\":$SP,\"quantity\":1}"
  api POST /api/v1/orders "$1" "$ADDR"
  OID="$(echo "$BODY" | json 'd and d.get("id")')"
}
cancel() { api POST "/api/v1/orders/$2/cancel" "$1"; }
stock() { sql "select quantity from warehouse.stock_items where product_id = $1"; }
restored() { sql "select count(*) from warehouse.stock_movements where order_id = $1 and type = 'ORDER_RESTORED'"; }
queue_col() {  # queue column -> value of `artemis queue stat` (3 consumers, 5 messages)
  scripts/broker stat 2>/dev/null | awk -v q="$1" -v c="$2" '$1 == q { print $c }'
}
consumers() { queue_col "awesome.commerce.events.$1" 2; }
waiting() { queue_col "$1" 3; }
relay_pending() {
  inside -s --max-time 10 http://backend:4001/actuator/prometheus | awk '/^events_relay_pending/ { printf "%d\n", $2 }'
}
cursor() { sql "select coalesce(max(last_sequence), 0) from $1.event_cursors"; }

section "Compose configurations"
for files in "docker-compose.yml" "docker-compose.yml docker-compose.chaos.yml" \
             "lightweight-docker-compose.yml docker-compose.broker.yml" \
             "lightweight-docker-compose.yml docker-compose.broker.yml docker-compose.chaos.yml" \
             "lightweight-docker-compose.yml docker-compose.broker.yml docker-compose.chaos.yml docker-compose.tracing.yml docker-compose.monitoring.yml"; do
  args=(); for f in $files; do args+=(-f "$f"); done
  if docker compose "${args[@]}" config --quiet; then ok "$files"; else bad "$files" "config failed"; fi
done
env_of() {  # service variable files... -> value
  local service="$1" var="$2"; shift 2
  local args=(); for f in "$@"; do args+=(-f "$f"); done
  docker compose "${args[@]}" config --format json | json "(d['services']['$service'].get('environment') or {}).get('$var')"
}
for svc in backend warehouse-service payment-service notification-service; do
  check "full: $svc EVENTS_TRANSPORT" "$(env_of "$svc" EVENTS_TRANSPORT docker-compose.yml)" broker
  check "lightweight: $svc keeps the feed" "$(env_of "$svc" EVENTS_TRANSPORT lightweight-docker-compose.yml)" None
  check "lightweight + broker: $svc EVENTS_TRANSPORT" \
    "$(env_of "$svc" EVENTS_TRANSPORT lightweight-docker-compose.yml docker-compose.broker.yml)" broker
done
check "lightweight + broker: warehouse reaches activemq directly" \
  "$(env_of warehouse-service SPRING_ARTEMIS_BROKER_URL lightweight-docker-compose.yml docker-compose.broker.yml)" "tcp://activemq:61616"
port=16161
for svc in backend warehouse-service payment-service notification-service; do
  check "lightweight + broker + chaos: $svc reaches activemq through toxiproxy:$port" \
    "$(env_of "$svc" SPRING_ARTEMIS_BROKER_URL lightweight-docker-compose.yml docker-compose.broker.yml docker-compose.chaos.yml)" \
    "tcp://toxiproxy:$port"
  port=$((port + 10000))
done
check "server: aitesters-backend publishes to its own address" \
  "$(env_of aitesters-backend EVENTS_BROKER_ADDRESS docker-compose.server.yml)" aitesters.commerce.events
check "server: activemq loads the commerce event topology" \
  "$(docker compose -f docker-compose.server.yml config --format json | json "' '.join(d['services']['activemq']['command'])")" \
  "run --properties /var/lib/artemis-config/commerce-events.properties"

section "Start lightweight + broker + chaos ($COMPOSE_PROJECT_NAME, gateway $B)"
[ "${BROKER_VERIFY_PULL:-true}" = true ] && "${compose[@]}" pull --ignore-buildable --quiet
up_out="$(scripts/chaos up lightweight broker)"; printf '%s\n' "$up_out" | tail -n 4
printf '%s\n' "$up_out" | grep -qF "Artemis console: http://127.0.0.1:$ARTEMIS_CONSOLE_PORT/console" \
  && ok "chaos up prints the Artemis console" || bad "Artemis console line" "$(printf '%s\n' "$up_out" | tail -n 3)"
running="$(docker ps --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" --format '{{.Label "com.docker.compose.service"}}' | sort | tr '\n' ' ')"
case " $running " in *" activemq "*) ok "activemq runs" ;; *) bad "activemq runs" "$running"; exit 1 ;; esac

section "Topology"
stat_out="$(scripts/broker stat)"; printf '%s\n' "$stat_out" | sed 's/^/    /'
for svc in warehouse-service payment-service notification-service; do
  check "$svc listens on its queue" "$(wait_for 90 "consumers $svc" 1)" 1
  printf '%s\n' "$stat_out" | grep -q "^DLQ.awesome.commerce.events.$svc " \
    && ok "DLQ.awesome.commerce.events.$svc exists" || bad "DLQ of $svc" "$stat_out"
done
code="$(curl -s -o /dev/null -w '%{http_code}' -u admin:admin "http://127.0.0.1:$ARTEMIS_CONSOLE_PORT/console/")"
case "$code" in 200|302) ok "Artemis console answers ($code)" ;; *) bad "Artemis console" "$code" ;; esac

A="$(signin admin 'LocalDemoAdmin123!')"
u="bv$RANDOM$RANDOM"
api POST /api/v1/users/signup "" "{\"username\":\"$u\",\"email\":\"$u@example.com\",\"password\":\"Broker12345!\",\"firstName\":\"Broker\",\"lastName\":\"Tester\",\"roles\":[\"ROLE_CLIENT\"]}"
T="$(signin "$u" 'Broker12345!')"
[ -n "$A" ] && [ "$T" != None ] && ok "admin and a fresh client signed in" || { bad "sign-in" "$BODY"; exit 1; }

section "Delivery through Artemis"
wc_before="$(cursor warehouse)"; pc_before="$(cursor payment)"
new_order "$T"; O1="$OID"; check "checkout -> 201" "$CODE" 201
api POST /api/v1/payments "$T" "{\"orderId\":$O1,\"card\":{\"number\":\"4242424242424242\",\"expiryMonth\":12,\"expiryYear\":2031,\"cvc\":\"123\",\"holderName\":\"Broker Tester\"}}" \
  -H "Idempotency-Key: $RUN-$O1"
PID="$(echo "$BODY" | json 'd and d.get("id")')"
check "card captured" "$(echo "$BODY" | json 'd and d.get("status")')" CAPTURED
check "order PAID" "$(wait_for 30 "api GET /api/v1/orders/$O1 $T; echo \$BODY | json 'd[\"status\"]'" PAID)" PAID
start=$(date +%s)
cancel "$T" "$O1"; check "cancel -> 200" "$CODE" 200
check "warehouse-service restored the stock" "$(wait_for 30 "restored $O1" 1)" 1
took=$(( $(date +%s) - start ))
[ "$took" -le 6 ] && ok "restore arrived ${took}s after the cancel (feed: settle 3 s + poll 5 s)" || bad "restore latency" "${took}s"
check "payment-service refunded the card" \
  "$(wait_for 30 "api GET /api/v1/payments/$PID $T; echo \$BODY | json 'd[\"status\"]'" REFUNDED)" REFUNDED
check "warehouse feed cursor did not move" "$(cursor warehouse)" "$wc_before"
check "payment feed cursor did not move" "$(cursor payment)" "$pc_before"
check "relay backlog empty" "$(wait_for 10 relay_pending 0)" 0
notification_handled() { "${compose[@]}" logs --no-color notification-service 2>/dev/null | grep -c 'from the broker' || true; }
check "notification-service handled events from the broker" \
  "$(wait_for 30 "[ \"\$(notification_handled)\" -ge 1 ] && echo yes" yes)" yes
check "no consumer lost its broker session" \
  "$("${compose[@]}" logs --no-color warehouse-service payment-service notification-service 2>/dev/null | grep -c 'Session is closed' || true)" 0

section "Poison message: five deliveries, then the dead-letter queue"
scripts/broker poison warehouse >/dev/null
check "DLQ.awesome.commerce.events.warehouse-service holds it" \
  "$(wait_for 60 "waiting DLQ.awesome.commerce.events.warehouse-service" 1)" 1
check "the warehouse queue is empty again" "$(waiting awesome.commerce.events.warehouse-service)" 0
n="$("${compose[@]}" logs --no-color warehouse-service 2>/dev/null | grep -c 'rolled back for redelivery' || true)"
[ "${n:-0}" -ge 5 ] && ok "warehouse-service rolled it back $n times" || bad "rollbacks" "$n"
new_order "$T"; O2="$OID"; cancel "$T" "$O2"
check "the next cancellation is still restored" "$(wait_for 30 "restored $O2" 1)" 1
scripts/broker dlq warehouse | grep -q 'is not a feed event' && ok "scripts/broker dlq shows the body" || bad "dlq browse"
scripts/broker redrive warehouse >/dev/null
check "redrive empties the DLQ" "$(wait_for 10 "waiting DLQ.awesome.commerce.events.warehouse-service" 0)" 0
check "and it fails five more times back into the DLQ" \
  "$(wait_for 60 "waiting DLQ.awesome.commerce.events.warehouse-service" 1)" 1
scripts/broker purge-dlq warehouse >/dev/null
check "purge-dlq empties it" "$(waiting DLQ.awesome.commerce.events.warehouse-service)" 0

section "Consumer down: the backlog waits in its queue"
# Checkout reserves stock synchronously in warehouse-service, so the order comes first.
new_order "$T"; O3="$OID"
"${compose[@]}" stop warehouse-service >/dev/null 2>&1
cancel "$T" "$O3"; check "cancel -> 200 while warehouse-service is down" "$CODE" 200
check "order.cancelled and stock.restore-requested wait in the warehouse queue" \
  "$(wait_for 20 "waiting awesome.commerce.events.warehouse-service" 2)" 2
check "no restore yet" "$(restored "$O3")" 0
"${compose[@]}" start warehouse-service >/dev/null 2>&1
check "after start: restored" "$(wait_for 120 "restored $O3" 1)" 1
check "after start: queue drained" "$(wait_for 20 "waiting awesome.commerce.events.warehouse-service" 0)" 0

section "broker-down backend: the relay backlog grows, checkout keeps working"
chaos broker-down backend
new_order "$T"; O4="$OID"; check "checkout -> 201 without the broker" "$CODE" 201
cancel "$T" "$O4"; check "cancel -> 200 without the broker" "$CODE" 200
pending="$(wait_for 20 "[ \"\$(relay_pending)\" -ge 2 ] && echo yes" yes)"
check "events_relay_pending >= 2" "$pending" yes
sleep 3
check "no restore while the relay cannot publish" "$(restored "$O4")" 0
check "backend health stays UP" "$(inside -s -o /dev/null -w '%{http_code}' http://backend:4001/actuator/health)" 200
chaos heal
check "after heal: relay backlog drained" "$(wait_for 60 relay_pending 0)" 0
check "after heal: restored" "$(wait_for 30 "restored $O4" 1)" 1

section "broker-down payment: a consumer reconnects"
new_order "$T"; O5="$OID"
api POST /api/v1/payments "$T" "{\"orderId\":$O5,\"card\":{\"number\":\"4242424242424242\",\"expiryMonth\":12,\"expiryYear\":2031,\"cvc\":\"123\",\"holderName\":\"Broker Tester\"}}" \
  -H "Idempotency-Key: $RUN-$O5"
P5="$(echo "$BODY" | json 'd and d.get("id")')"
wait_for 30 "api GET /api/v1/orders/$O5 $T; echo \$BODY | json 'd[\"status\"]'" PAID >/dev/null
chaos broker-down payment
check "payment health stays UP without the broker" \
  "$(inside -s -o /dev/null -w '%{http_code}' http://payment-service:4004/actuator/health)" 200
cancel "$T" "$O5"
check "the refund request waits in the payment queue" \
  "$(wait_for 20 "waiting awesome.commerce.events.payment-service" 1)" 1
chaos heal
check "after heal: card refunded" \
  "$(wait_for 60 "api GET /api/v1/payments/$P5 $T; echo \$BODY | json 'd[\"status\"]'" REFUNDED)" REFUNDED
check "after heal: payment queue drained" "$(wait_for 20 "waiting awesome.commerce.events.payment-service" 0)" 0
