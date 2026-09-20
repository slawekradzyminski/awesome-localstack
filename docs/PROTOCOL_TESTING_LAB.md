# Compare REST, GraphQL, and gRPC

These are additional testing surfaces over the same inventory services and
transactions. REST remains the frontend default. GraphQL is always included in
the updated backend; the native gRPC listener is optional and exposes only four
admin inventory RPCs. Application release 3.8.0 includes these features; see the
[release record](GRAPHQL_GRPC_RELEASE.md) for public rollout verification.

Swagger documents REST. Explore GraphQL at `/api/v1/graphiql`, with its schema
sidebar and autocomplete. Use the checked-in Protobuf contract with grpcurl or
Postman for gRPC; these RPCs are not Swagger endpoints. See
[gRPC setup](GRPC_INVENTORY.md) to enable the local listener.

## Prepare the session

Use a disposable local stack and an admin JWT from its normal REST sign-in.
Create a product with stock quantity 5 using the existing product API or UI.
Record its numeric ID. Open the frontend Traffic Monitor, wait for **Connected**,
and copy its **Traffic session ID**. It is a browser client-session routing value, not a JWT or
an authorization substitute. Same-origin tabs share the stored traffic session. In GraphiQL's Headers editor use:

```json
{
  "Authorization": "Bearer <ADMIN_JWT>",
  "X-Client-Session-Id": "<TRAFFIC_SESSION_ID>"
}
```

For shell examples, set local values without committing credentials:

```bash
export BASE_URL=http://localhost:4001
export GRPC_ADDRESS=127.0.0.1:9091
export PROTO_ROOT=../test-secure-backend/src/main/proto
export PRODUCT_ID=1                  # replace with your fixture ID
export REQUEST_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
read -rs ADMIN_JWT; export ADMIN_JWT
read -r TRAFFIC_SESSION_ID; export TRAFFIC_SESSION_ID
```

The disposable compatibility stack uses ports 14001 (HTTP), 14081 (gateway), and
14991 (gRPC). Use the ports of the stack you started. grpcurl and jq must be on
PATH. Run the following from `awesome-localstack`.

## One write, three protocols, one stock change

Given stock 5, apply a +3 adjustment through REST:

```bash
jq -n --arg requestId "$REQUEST_ID" \
  '{delta:3,reason:"Training restock",requestId:$requestId}' > /tmp/restock.json
curl --fail-with-body -sS "$BASE_URL/api/v1/admin/inventory/$PRODUCT_ID/adjustments" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "X-Client-Session-Id: $TRAFFIC_SESSION_ID" \
  -H 'Content-Type: application/json' --data-binary @/tmp/restock.json
```

Then replay that exact adjustment through GraphQL, retaining the request ID:

```bash
jq -n --rawfile query examples/protocols/adjust-inventory.graphql \
  --arg productId "$PRODUCT_ID" --slurpfile input /tmp/restock.json \
  '{query:$query,variables:{productId:$productId,input:$input[0]}}' > /tmp/restock-graphql.json
curl --fail-with-body -sS "$BASE_URL/api/v1/graphql" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "X-Client-Session-Id: $TRAFFIC_SESSION_ID" \
  -H 'Content-Type: application/json' --data-binary @/tmp/restock-graphql.json
```

Finally replay through native gRPC:

```bash
jq --arg productId "$PRODUCT_ID" '. + {productId:$productId}' /tmp/restock.json |
  grpcurl -plaintext -max-time 5 \
    -H "authorization: Bearer $ADMIN_JWT" \
    -H "x-client-session-id: $TRAFFIC_SESSION_ID" \
    -import-path "$PROTO_ROOT" -proto awesome/inventory/v1/inventory.proto \
    -d @ "$GRPC_ADDRESS" awesome.inventory.v1.InventoryService/AdjustStock
```

Expect the same movement ID and quantity 8 from all three calls, with one stock
movement. The GraphQL response has this shape (IDs vary):

```json
{"data":{"adjustInventory":{"id":"42","quantityAfter":8,"requestId":"<REQUEST_ID>"}}}
```

Read stock through REST `GET /api/v1/admin/inventory/{productId}`, the
[inventory query](../examples/protocols/inventory.graphql) and its
[variables](../examples/protocols/inventory.variables.json), and native GetStock:

```bash
grpcurl -plaintext -max-time 5 \
  -H "authorization: Bearer $ADMIN_JWT" \
  -H "x-client-session-id: $TRAFFIC_SESSION_ID" \
  -import-path "$PROTO_ROOT" -proto awesome/inventory/v1/inventory.proto \
  -d "{\"productId\":\"$PRODUCT_ID\"}" "$GRPC_ADDRESS" \
  awesome.inventory.v1.InventoryService/GetStock
```

All reads must observe 8. Protobuf int64 fields use strings in JSON. An omitted
optional `size` uses the server default; explicitly setting `size:0` is invalid.
Changing the delta while reusing the request ID must fail: REST 409, GraphQL
`CONFLICT`, gRPC `FAILED_PRECONDITION`. Reuse the same ID for an uncertain retry;
a fresh ID represents a new write. A client deadline expiring does not prove
that a database write was cancelled.

## Compare failures and privacy

Given a customer JWT, execute the [partial-error query](../examples/protocols/partial-error.graphql)
with a different customer's username. With `Accept: application/json`, expect
HTTP 200 plus `data.products`, null `data.cart`, and an error whose extension code
is `FORBIDDEN`. The monitor shows **Partial error · HTTP 200**, in red. Test the
GraphQL `errors` array as well as HTTP status. With
`application/graphql-response+json`, request-level validation errors can use a
non-200 HTTP status; execution errors still need independent inspection.

Use the customer JWT for GetStock: expect gRPC **PERMISSION_DENIED (7)**.
Remove authentication: expect **UNAUTHENTICATED (16)**. Successful gRPC operations
show **OK (0)**; the number is a native gRPC code, not an HTTP status.

New protocol capture requires a valid explicit `X-Client-Session-Id` header
(lowercase metadata key for gRPC). Without it, requests still work but produce
no protocol traffic record. Existing REST capture behavior stays unchanged.
Health and reflection RPCs are deliberately excluded from operation capture.

Each new event contains protocol, canonical operation, duration, outcome,
canonical error codes, and a generated correlation ID. GraphQL returns the ID
in `X-Correlation-Id`; gRPC returns it in trailers when the call closes normally.
Cancelled clients may not receive trailers. Retrieve the saved record via
`GET /api/v1/traffic/logs/{correlationId}` with the same traffic session header.
The existing REST log envelope is retained; new protocol records use method
`GRAPHQL` or `GRPC` and store their safe summary in `responseBody`.

Protocol capture never stores documents, variables, aliases, client-supplied
operation names, query strings, message bodies, JWTs, headers, shipping addresses,
or raw error descriptions—even when legacy REST obfuscation is disabled.
GraphQL summaries use only known root fields (at most eight), and fragment-only
selections may show just `query` or `mutation`. Error codes are allowlisted and
bounded. No new metrics with user-controlled labels are introduced. Existing
REST logging and its privacy settings remain separate.

The monitor uses the existing session-scoped subscription and log access policy.
A session ID is not proof of ownership: keep it private, just like the existing
traffic-viewer capability. The optional legacy public traffic mode remains
public; use the normal session-scoped configuration for private training.

When evolving the Protobuf schema, preserve field numbers and wire types;
reserve removed field names/numbers and keep presence semantics explicit.
These exercises are additional protocol checks, separate from the frozen
`ai-testers-api` compatibility assertions.
