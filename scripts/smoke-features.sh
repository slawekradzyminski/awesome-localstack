#!/usr/bin/env bash
# Curl checks of the recently added features.
#   scripts/smoke-features.sh <base-url> client   customer-level checks (safe on production)
#   scripts/smoke-features.sh <base-url> full     + admin and warehouse flows (local demo accounts)
set -uo pipefail
B=$1; MODE=${2:-client}
PASS=0; FAIL=0; RUN=$(date +%H%M%S)-$RANDOM
ok()   { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s -- %s\n' "$1" "${2:-}"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected '$3', got '$2'"; fi; }
section(){ printf '\n== %s\n' "$1"; }
J='Content-Type: application/json'
# api METHOD PATH TOKEN [BODY] [extra curl args...] -> body in $BODY, status in $CODE, headers in $HDRS
api() {
  local m=$1 p=$2 t=$3 d=${4:-}; shift 4 2>/dev/null || shift $#
  local out; out=$(mktemp); HDRS=$(mktemp)
  local args=(-s -o "$out" -D "$HDRS" -w '%{http_code}' -X "$m" "$B$p" -H "$J" -H "X-Request-Id: nf-$RUN-$RANDOM")
  [ -n "$t" ] && args+=(-H "Authorization: Bearer $t")
  [ -n "$d" ] && args+=(-d "$d")
  CODE=$(curl "${args[@]}" "$@"); BODY=$(cat "$out"); rm -f "$out"
}
signup_signin() {  # -> token of a fresh client
  local u=nf$1$RANDOM
  api POST /api/v1/users/signup "" "{\"username\":\"$u\",\"email\":\"$u@example.com\",\"password\":\"NewFeature123!\",\"firstName\":\"Feat\",\"lastName\":\"Tester\",\"roles\":[\"ROLE_CLIENT\"]}"
  api POST /api/v1/users/signin "" "{\"username\":\"$u\",\"password\":\"NewFeature123!\"}"
  echo "$BODY" | jq -r .token
}
signin() { api POST /api/v1/users/signin "" "{\"username\":\"$1\",\"password\":\"$2\"}"; echo "$BODY" | jq -r .token; }
order_for() {  # token country -> order json in $ORDER
  api GET "/api/v1/products/search?inStock=true&sort=price_asc&size=1" "$1"; local pid; pid=$(echo "$BODY" | jq -r '.content[0].id')
  api POST /api/v1/cart/items "$1" "{\"productId\":$pid,\"quantity\":1}"
  api POST /api/v1/orders "$1" "{\"street\":\"Marszalkowska 1\",\"city\":\"Warszawa\",\"state\":\"M\",\"zipCode\":\"00-001\",\"country\":\"$2\"}"
  ORDER=$BODY
}
pay() {  # token orderId card -> payment json in $PAY
  api POST /api/v1/payments "$1" "{\"orderId\":$2,\"card\":{\"number\":\"$3\",\"expiryMonth\":12,\"expiryYear\":2031,\"cvc\":\"123\",\"holderName\":\"Feat Tester\"}}" -H "Idempotency-Key: nf-$RUN-$RANDOM$RANDOM"
  PAY=$BODY
}
order_status() { api GET "/api/v1/orders/$2" "$1"; echo "$BODY" | jq -r .status; }
wait_for() {  # seconds cmd expected -> polls until cmd outputs expected
  local s=$1 want=$3 got=""; for _ in $(seq 1 "$s"); do got=$(eval "$2"); [ "$got" = "$want" ] && break; sleep 1; done; echo "$got"
}

echo "Target: $B ($MODE)   run id: $RUN"
T=$(signup_signin a); T2=$(signup_signin b)
[ -n "$T" ] && [ "$T" != null ] && ok "sign-up and sign-in of a fresh client" || { bad "sign-in" "$BODY"; exit 1; }

section "Correlation IDs"
code=$(curl -s -o /dev/null -D - "$B/v3/api-docs" -H "X-Request-Id: nf-corr-$RUN" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-request-id"{print $2}')
check "valid X-Request-Id is echoed" "$code" "nf-corr-$RUN"
code=$(curl -s -o /dev/null -D - "$B/v3/api-docs" -H 'X-Request-Id: bad id!<x>' | tr -d '\r' | awk -F': ' 'tolower($1)=="x-request-id"{print $2}')
[ -n "$code" ] && [ "$code" != 'bad id!<x>' ] && ok "invalid X-Request-Id is replaced ($code)" || bad "invalid id replaced" "$code"

section "Gateway: unknown API paths"
for p in /api /api/ /api/v2/users /api/nope/deeper; do
  api GET "$p" ""
  check "$p -> 404" "$CODE" 404
  check "$p answers the JSON error shape" "$(echo "$BODY" | jq -r .message 2>/dev/null)" "Not found"
done
spa=$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$B/no-such-page")
case "$spa" in "200 text/html"*) ok "non-API unknown path still reaches the SPA ($spa)";; *) bad "SPA fallback" "$spa";; esac

section "Product search"
api GET "/api/v1/products/search?q=phone&sort=price_desc&size=5" "$T"
check "search returns 200" "$CODE" 200
[ "$(echo "$BODY" | jq '.facets.categories | length')" -gt 0 ] && ok "facets present ($(echo "$BODY" | jq -c '[.facets.categories[].value]'))" || bad "facets" "$BODY"
api GET "/api/v1/products/search?minPrice=500&maxPrice=10" "$T"; check "minPrice > maxPrice is 400" "$CODE" 400
api GET "/api/v1/products" "$T"; check "plain product list is still an array" "$(echo "$BODY" | jq -r type)" array

section "VAT and currencies"
api GET "/api/v1/vat-rates/Poland" "$T"; check "VAT rate for Poland" "$(echo "$BODY" | jq -r .rate)" 23.00
api GET "/api/v1/currencies/convert?amount=100&from=USD&to=EUR" "$T"
[ "$CODE" = 200 ] && ok "convert 100 USD -> $(echo "$BODY" | jq -r .converted) EUR" || bad "currency convert" "$BODY"
order_for "$T" Poland
check "order to Poland carries taxRate 23" "$(echo "$ORDER" | jq -r ".taxRate == 23")" true
check "order status is still PENDING (l20 contract)" "$(echo "$ORDER" | jq -r .status)" PENDING
# Stock reservation with a time limit (backend 3.21.0): the hold expires.
[ "$(echo "$ORDER" | jq -r '.reservationExpiresAt // empty')" ] \
  && ok "order carries reservationExpiresAt ($(echo "$ORDER" | jq -r .reservationExpiresAt))" \
  || bad "reservationExpiresAt" "$ORDER"
OID=$(echo "$ORDER" | jq -r .id); TOTAL=$(echo "$ORDER" | jq -r .totalAmount)

section "Webhooks (inbox + signature + SSRF), served by notification-service"
code=$(curl -s -o /dev/null -w '%{http_code}' "$B/notification/v3/api-docs"); check "notification-service OpenAPI through the gateway" "$code" 200
api POST /api/v1/webhook-inboxes "$T" ""; INBOX=$(echo "$BODY" | jq -r .token); INBOX_URL=$(echo "$BODY" | jq -r .url)
check "inbox created" "$CODE" 201
api POST /api/v1/webhooks "$T" "{\"url\":\"$INBOX_URL\",\"events\":[\"order.paid\",\"order.cancelled\",\"refund.booked\"],\"description\":\"curl check\"}"
check "subscription created" "$CODE" 201; SECRET=$(echo "$BODY" | jq -r .secret); WH=$(echo "$BODY" | jq -r .id)
api GET "/api/v1/webhooks/$WH" "$T"; check "secret is not returned again" "$(echo "$BODY" | jq -r '.secret // "absent"')" absent
for url in http://169.254.169.254/latest http://localhost/x http://backend:4001/internal http://10.0.0.1/; do
  api POST /api/v1/webhooks "$T" "{\"url\":\"$url\",\"events\":[\"order.paid\"]}"; check "SSRF rejected: $url" "$CODE" 400
done

section "Payments"
pay "$T" "$OID" 4000000000000002; check "declined card -> FAILED CARD_DECLINED" "$(echo "$PAY" | jq -r '.status+" "+.failureCode')" "FAILED CARD_DECLINED"
check "order stays PENDING after decline" "$(order_status "$T" "$OID")" PENDING
pay "$T" "$OID" 4000000000003220; PID3=$(echo "$PAY" | jq -r .id)
check "3-D Secure card -> REQUIRES_ACTION" "$(echo "$PAY" | jq -r .status)" REQUIRES_ACTION
api POST "/api/v1/payments/$PID3/3ds" "$T" '{"code":"123456"}'; check "3-D Secure code 123456 -> CAPTURED" "$(echo "$BODY" | jq -r .status)" CAPTURED
check "order becomes PAID via signed result" "$(wait_for 15 "order_status $T $OID" PAID)" PAID
api GET "/api/v1/orders/$OID/payments" "$T2"; check "other user's order payments -> 404" "$CODE" 404
api GET "/api/v1/loyalty" "$T"; pts=$(echo "$BODY" | jq -r .balance)
[ "$pts" -gt 0 ] 2>/dev/null && ok "loyalty points earned on PAID ($pts)" || bad "loyalty points" "$BODY"

KEY="nf-idem-$RUN"; order_for "$T" Germany; O2=$(echo "$ORDER" | jq -r .id)
api POST /api/v1/payments "$T" "{\"orderId\":$O2,\"card\":{\"number\":\"4000000000000077\",\"expiryMonth\":12,\"expiryYear\":2031,\"cvc\":\"123\",\"holderName\":\"Feat Tester\"}}" -H "Idempotency-Key: $KEY"
check "async card -> PROCESSING" "$(echo "$BODY" | jq -r .status)" PROCESSING; P2=$(echo "$BODY" | jq -r .id)
api POST /api/v1/payments "$T" "{\"orderId\":$O2,\"card\":{\"number\":\"4000000000000077\",\"expiryMonth\":12,\"expiryYear\":2031,\"cvc\":\"123\",\"holderName\":\"Feat Tester\"}}" -H "Idempotency-Key: $KEY"
check "same Idempotency-Key replays the payment" "$(echo "$BODY" | jq -r .id) $(grep -i '^idempotent-replayed' "$HDRS" | tr -d '\r' | awk '{print $2}')" "$P2 true"
check "async payment settles to CAPTURED" "$(wait_for 40 "api GET /api/v1/payments/$P2 $T; echo \$BODY | jq -r .status" CAPTURED)" CAPTURED

section "Commerce emails (notification-service, from notification.requested feed events)"
check "PAYMENT_RECEIVED recorded for the customer" \
  "$(wait_for 30 "api GET '/api/v1/notifications/emails?size=20' $T; echo \$BODY | jq -r '[.content[].template] | index(\"PAYMENT_RECEIVED\") != null'" true)" true
api GET "/api/v1/notifications/emails" "$T2"; check "another customer sees no emails of this one" "$(echo "$BODY" | jq -r '[.content[].template] | index("PAYMENT_RECEIVED") == null')" true
api GET "/api/v1/notifications/emails" ""; check "email log needs a token" "$CODE" 401

section "Event feed: cancel a card-paid order -> card refunded"
api POST "/api/v1/orders/$OID/cancel" "$T" ""; check "cancel paid order" "$CODE" 200
check "payment-service refunds via the feed" "$(wait_for 40 "api GET /api/v1/payments/$PID3 $T; echo \$BODY | jq -r .status" REFUNDED)" REFUNDED

section "Webhook deliveries in the inbox"
sleep 5; api GET "/api/v1/webhook-inboxes/$INBOX/requests" "$T"; types=$(echo "$BODY" | jq -r '[.[].headers["X-Webhook-Event"] // .[].headers["x-webhook-event"]] | unique | join(",")')
echo "$types" | grep -q order.paid && echo "$types" | grep -q order.cancelled && ok "inbox received $types" || bad "inbox events" "$types"
req=$(echo "$BODY" | jq -c '[.[] | select(.body | contains("order.cancelled"))][0]')
sig=$(echo "$req" | jq -r '.headers["X-Webhook-Signature"] // .headers["x-webhook-signature"]'); body=$(echo "$req" | jq -r .body)
t=${sig#t=}; t=${t%%,*}; v1=${sig##*v1=}
mine=$(printf '%s.%s' "$t" "$body" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')
check "HMAC signature verifies with the secret" "$mine" "$v1"
echo "$req" | jq -e '.headers["X-Request-Id"] // .headers["x-request-id"]' >/dev/null && ok "delivery carries X-Request-Id" || bad "delivery X-Request-Id" "$req"

section "Tracking (public)"
api GET "/api/v1/tracking/NOPE123" ""; check "unknown tracking number -> 404 without login" "$CODE" 404

if [ "$MODE" = full ]; then
  section "Admin: gift card + points at checkout"
  A=$(signin admin 'LocalDemoAdmin123!'); W=$(signin warehouse warehouse)
  api POST /api/v1/admin/gift-cards "$A" '{"amount":20.00,"note":"curl check"}'; GC=$(echo "$BODY" | jq -r .code); check "admin issues gift card" "$CODE" 201
  api GET "/api/v1/gift-cards/$GC" "$T"; check "customer sees balance" "$(echo "$BODY" | jq -r .balance)" 20.00
  api GET "/api/v1/products/search?inStock=true&sort=price_desc&size=1" "$T"; pid=$(echo "$BODY" | jq -r '.content[0].id')
  api POST /api/v1/cart/items "$T" "{\"productId\":$pid,\"quantity\":1}"
  api PUT /api/v1/cart/gift-card "$T" "{\"code\":\"$GC\"}"; check "gift card applied to cart" "$(echo "$BODY" | jq -r .giftCardAmount)" 20.00
  api POST /api/v1/orders "$T" '{"street":"Main 1","city":"Berlin","state":"BE","zipCode":"10115","country":"DE"}'; O3=$(echo "$BODY" | jq -r .id)
  check "order amountDue = total - 20" "$(echo "$BODY" | jq -r '(.totalAmount - .amountDue)')" 20
  pay "$T" "$O3" 4242424242424242; check "card pays amountDue" "$(echo "$PAY" | jq -r '.status')" CAPTURED
  check "order PAID" "$(wait_for 15 "order_status $T $O3" PAID)" PAID

  section "Reservations: admin expires a PENDING order's hold"
  order_for "$T" Poland; O4=$(echo "$ORDER" | jq -r .id)
  api POST "/api/v1/admin/orders/$O4/expire-reservation" "$A" ""; check "expire-reservation -> 200" "$CODE" 200
  check "expired order is CANCELLED" "$(wait_for 15 "order_status $T $O4" CANCELLED)" CANCELLED
  api POST "/api/v1/admin/orders/$O4/expire-reservation" "$A" ""; check "expiring a non-PENDING order -> 409" "$CODE" 409

  section "Warehouse: simulated carrier tracking"
  api POST /api/v1/warehouse/shipments "$W" "{\"orderId\":$O3}"; SID=$(echo "$BODY" | jq -r .id); check "shipment created" "$CODE" 201
  api POST "/api/v1/warehouse/shipments/$SID/pick" "$W" ""; api POST "/api/v1/warehouse/shipments/$SID/pack" "$W" '{"weightKg":1.2}'
  api POST "/api/v1/warehouse/shipments/$SID/ship" "$W" '{"carrier":"DHL"}'; TN=$(echo "$BODY" | jq -r .trackingNumber)
  check "ship without number -> simulated" "$CODE" 200
  api GET "/api/v1/orders/$O3/shipments" "$T"; check "parcels list through the gateway (warehouse-service)" "$CODE" 200
  [ "$(echo "$BODY" | jq -r '.[0].locationCode // empty')" ] && ok "parcel 1 of $(echo "$BODY" | jq -r '.[0].parcelCount') ships from $(echo "$BODY" | jq -r '.[0].locationCode')" \
    || bad "parcel location" "$BODY"
  for _ in 1 2 3 4 5 6; do api POST "/api/v1/warehouse/shipments/$SID/carrier/advance" "$W" ""; done
  api GET "/api/v1/tracking/$TN" ""; check "public tracking shows DELIVERED" "$(echo "$BODY" | jq -r .currentStatus)" DELIVERED
  check "order DELIVERED in backend" "$(wait_for 15 "order_status $T $O3" DELIVERED)" DELIVERED
fi

printf '\nResult: %s passed, %s failed\n' "$PASS" "$FAIL"; [ "$FAIL" = 0 ]
