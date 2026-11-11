# Tracing a request

Every request gets two correlation ids at the edge of the platform. They are
logged by every hop and travel with the work through service calls, the event
feed and the outboxes, so one id finds everything that happened because of one
click or one API call.

| Header | Format | Purpose |
| --- | --- | --- |
| `X-Request-Id` | 1–128 characters of `A-Z a-z 0-9 . _ -` | The id people search for. Returned to the client on every response. |
| `traceparent` | W3C: `00-<32 hex trace id>-<16 hex parent id>-<2 hex flags>`, neither id all zeros | The trace id groups all hops; each hop gets a new parent (span) id. |

## Where the ids come from

The gateway (and on the server the edge in front of it) **keeps a valid
incoming value and replaces anything else**:

- `X-Request-Id`: a valid incoming value is kept, otherwise nginx's
  `$request_id` (32 random hex characters) is used;
- `traceparent`: a valid incoming value is kept, otherwise
  `00-<$request_id>-<last 16 hex of $request_id>-01` is generated. An
  uppercase, all-zero, wrong-version or malformed value counts as invalid.

So a test can send its own `X-Request-Id: checkout-test-17` and search for
exactly that; a browser that sends nothing gets a generated id, visible in the
response headers (developer tools → Network).

```mermaid
flowchart TB
    C([Browser or test]) -->|"X-Request-Id?<br/>traceparent?"| E[edge<br/>server only]
    E -->|"validated ids"| G[gateway]
    G -->|"X-Request-Id + traceparent"| B[backend]
    G --> W[warehouse-service]
    G --> P[payment-service]
    G -.->|"X-Request-Id on<br/>every response"| C
    B -->|"same transaction:<br/>request_id, trace_id"| F[("event feed<br/>domain_events")]
    F -.->|"polled with the ids"| W
    F -.->|"polled with the ids"| P
    W -->|"child traceparent"| B
    P -->|"child traceparent"| B
```

## How the ids flow

1. **Gateway.** Validates or generates both ids, passes them to every upstream
   (backend, warehouse-service, payment-service, frontend, docs), adds
   `X-Request-Id` to the response (replacing an upstream copy, so the client
   sees it once) and writes one JSON access-log line with both ids.
2. **Spring services** (backend 3.17.0, warehouse-service 1.4.0,
   payment-service 1.2.0). A `CorrelationFilter` validates the ids again, puts
   `requestId`, `traceId` and a new `spanId` into the logging context (MDC)
   and echoes `X-Request-Id`. On the server, logs are ECS JSON
   (`LOGGING_STRUCTURED_FORMAT_CONSOLE=ecs`), so these are JSON fields; locally
   they appear as `[traceId,requestId]` in the readable log line.
3. **Service calls.** warehouse-service and payment-service send the same
   `X-Request-Id` and a child `traceparent` (same trace id, new parent id)
   when they call the backend's internal API.
4. **Event feed.** The backend stores `request_id` and `trace_id` with each
   domain event, written in the transaction of the request that caused it,
   and logs one INFO line per event (`Recorded order.cancelled #42 for order 7`)
   under that request's ids, so the backend side shows up in the same search.
   A consumer handling the event (a card refund, a cancelled shipment) logs
   with those ids, so a refund processed seconds later by payment-service
   carries the id of the cancel request.
5. **Outboxes.** Emails, webhooks, warehouse notifications and payment results
   store the ids when they are enqueued and log them on delivery; webhook
   deliveries also send `X-Request-Id` (the delivery id stays in
   `X-Webhook-Id`). Work started by a scheduler without a request (a carrier
   step, a retention job) has no request id.

Until the service releases above are pinned, only the gateway part is active:
the gateway logs and returns the ids and passes them upstream, and the server
services already log JSON, without the id fields.

## Find everything about one request

Take the id from the response header (`X-Request-Id`) or from a gateway log
line, then search all containers of the stack.

On the server (`make ansible-ssh`, then in `/opt/awesome-localstack`):

```bash
ID=checkout-test-17
docker compose -p awesome-server logs --no-color --since 2h | grep -F "$ID"
```

The same as a time-ordered table (service, time, level or HTTP status,
message), one row per JSON line:

```bash
docker compose -p awesome-server logs --no-color --since 2h \
  | grep -F "$ID" \
  | jq -rR '
      capture("^(?<svc>[^ ]+) +[|] (?<line>.*)$") as $m
      | ($m.line | fromjson? // {message: $m.line}) as $e
      | [$m.svc,
         ($e.time // $e["@timestamp"] // ""),
         ($e["log.level"] // $e.log.level? // $e.status // "" | tostring),
         ($e.message // "\($e.method) \($e.uri) -> \($e.upstream) \($e.status) in \($e.request_time)s")]
      | @tsv' \
  | sort -t "$(printf '\t')" -k2,2
```

To follow work beyond the request (an event handled later by another
service), search for the **trace id** instead: it is the `trace_id` field of
the gateway line, or the `traceId` field of a service line.

```bash
TRACE=$(docker compose -p awesome-server logs --no-color --no-log-prefix gateway \
  | grep -F "\"request_id\":\"$ID\"" | jq -r .trace_id | head -1)
docker compose -p awesome-server logs --no-color --since 2h | grep -F "$TRACE"
```

The `aitesters.byst.re` sandbox runs in the same project: its services are the
`aitesters-*` rows of the same output.

Locally, use the profile's project instead (`awesome-light`,
`awesome-full-native`):

```bash
curl -si http://localhost:8081/api/v1/products -H 'X-Request-Id: local-check-1' | grep -i x-request-id
docker compose -p awesome-light logs --no-color | grep -F local-check-1
```

Local Spring logs stay human-readable, so the `jq` filter shows only the
gateway's JSON lines; the `grep` finds everything.

## Gateway access log fields

| Field | Meaning |
| --- | --- |
| `time` | ISO 8601 time the request finished |
| `request_id`, `trace_id`, `traceparent` | The ids after validation, exactly as sent upstream |
| `host`, `remote_addr`, `method`, `uri`, `user_agent` | The request (`uri` is the path without the query string, so tokens in query parameters are not logged) |
| `status`, `bytes_sent`, `request_time` | The response and total time in seconds |
| `upstream`, `upstream_status` | Address and status of the upstream; `-` or empty when nginx answered itself (a `404` for `/internal/`) |
| `upstream_connect_time`, `upstream_header_time`, `upstream_response_time` | Upstream timings in seconds; slow `upstream_header_time` with fast connect means the service, not the network |

On the server, both the edge and the gateway log a line for each request, with
the same ids. The gateway does not log `/images/` and `/branding/`.

## Guarantees

`scripts/verify-correlation-ids.py` (CI job `verifyCorrelationIds`) checks
that every server block of every gateway configuration logs JSON, returns
`X-Request-Id` and passes both headers from every proxied location, and that
the server's Spring services enable ECS logging. With `--routing` it starts
the pinned nginx with stub upstreams and proves that ids are generated,
preserved when valid, replaced when invalid, passed to every upstream and
echoed back once, through the edge as well.
