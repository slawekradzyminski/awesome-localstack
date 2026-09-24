# Run a gRPC inventory exercise

Native gRPC is a small, admin-only inventory API. It has four unary RPCs:
`GetStock`, `ListInventory`, `AdjustStock`, and `ListStockMovements`. It is useful
for comparing a versioned Protobuf contract, metadata authentication, native
status codes, and idempotent writes with the existing REST and GraphQL APIs.
The storefront does not call gRPC; Swagger does not list these RPCs.

## Choose the training setup

| Participant | Recommended setup | Access needed |
| --- | --- | --- |
| Student doing the exercise | Run the published 3.8.0 stack locally with the gRPC Compose override | Docker Compose, `grpcurl`, `curl`, `jq`, and this repository; no server SSH access |
| Instructor demonstrating the deployed sandbox | Open an SSH tunnel on the instructor's machine and screen-share the calls | Existing production SSH/Vault access, `grpcurl`, and a sandbox admin JWT |

There is **no public native gRPC URL**. The production listeners bind to server
loopback. A remote student cannot point Postman or grpcurl at
`aitesters.byst.re:9092`; the public nginx routes serve REST and GraphQL only.
Give students the local exercise below rather than distributing server SSH keys
or exposing the listener on a public interface.

## Student: run the local exercise

Use a local checkout of `awesome-localstack`. If the lightweight stack is
already running, keep it running and check only that host port 9091 is free.
For a fresh stack, ports 8081, 8082, 9091, and 11434 must be free. The
published backend image already contains gRPC; students do not need to build
Java or clone the backend source. The second Compose file is the Docker-level
gRPC switch: applying it recreates the backend with the listener while keeping
the other lightweight services. From the repository root, run:

```bash
docker compose -f lightweight-docker-compose.yml -f docker-compose.grpc.yml config --quiet
docker compose -f lightweight-docker-compose.yml -f docker-compose.grpc.yml up -d
docker compose -f lightweight-docker-compose.yml -f docker-compose.grpc.yml ps
```

Wait for the backend to become healthy. Open the
[local storefront](http://localhost:8081/login) and sign in with the documented
local demo admin (`admin` / `LocalDemoAdmin123!`). The local Swagger UI is at
`http://localhost:8081/swagger-ui/index.html`; it remains a REST explorer.

Fetch the single-file Protobuf contract and obtain an admin JWT through the
existing REST sign-in. These commands are for the disposable local demo account:

```bash
mkdir -p /tmp/awesome-grpc
curl -fsSLo /tmp/awesome-grpc/inventory.proto \
  https://raw.githubusercontent.com/slawekradzyminski/test-secure-backend/master/src/main/proto/awesome/inventory/v1/inventory.proto
export ACCESS_TOKEN="$(curl -fsS http://localhost:8081/api/v1/users/signin \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"LocalDemoAdmin123!"}' | jq -r .token)"
test -n "$ACCESS_TOKEN" && test "$ACCESS_TOKEN" != null
```

List the seeded inventory. Reflection is disabled, so each grpcurl call must
specify the downloaded `.proto` file:

```bash
grpcurl -plaintext -max-time 5 \
  -import-path /tmp/awesome-grpc -proto inventory.proto \
  -H "authorization: Bearer $ACCESS_TOKEN" \
  -d '{"size":5}' 127.0.0.1:9091 \
  awesome.inventory.v1.InventoryService/ListInventory
```

Copy a returned `productId` and replace `1` in this read:

```bash
grpcurl -plaintext -max-time 5 \
  -import-path /tmp/awesome-grpc -proto inventory.proto \
  -H "authorization: Bearer $ACCESS_TOKEN" \
  -d '{"productId":"1"}' 127.0.0.1:9091 \
  awesome.inventory.v1.InventoryService/GetStock
```

Try the same read without the `authorization` metadata: expect
`UNAUTHENTICATED`. Sign in as the local `client` account and send its token:
expect `PERMISSION_DENIED`. For a write exercise, create a disposable product,
then follow the [protocol testing lab](PROTOCOL_TESTING_LAB.md): adjust its stock
once, replay the identical request ID through REST and GraphQL, and verify one
adjustment movement. Do not use a shared or stable product for that exercise.

To see native events in the UI, open `http://localhost:8081/traffic`, copy its
**Traffic session ID**, and add
`-H "x-client-session-id: <TRAFFIC_SESSION_ID>"` to grpcurl. This header routes
the event to that monitor; it does not grant authorization. When finished, stop
the listener without tearing down the stack with
`docker compose -f lightweight-docker-compose.yml up -d --force-recreate backend`.
To stop the disposable stack entirely, use the two Compose files and `down`.

## Instructor: demonstrate the deployed sandbox

The instructor can use the existing Vault-managed SSH settings to forward the
server's loopback listeners. From this repository, run in a separate terminal:

```bash
eval "$(cd ansible && ./resolve-ssh-vars.sh)"
ssh -o StrictHostKeyChecking=accept-new -N \
  -L 14992:127.0.0.1:9092 \
  -p "$SSH_PORT" -i "$SSH_KEY_PATH" "$SSH_USER@$SSH_HOST"
```

Use a JWT obtained from `https://aitesters.byst.re/api/v1/users/signin`, then
run the same grpcurl examples against `127.0.0.1:14992`. Use the sandbox's
[Traffic Monitor](https://aitesters.byst.re/traffic) and its session ID when
demonstrating event capture. Keep any write exercise on a unique disposable
product and remove it afterwards. Stable credentials and sandbox credentials
cannot be interchanged.

The [backend gRPC guide](https://github.com/slawekradzyminski/test-secure-backend/blob/master/docs/GRPC.md)
describes every RPC, status mapping, pagination default, deadline, and retry
rule. The [Protobuf contract](https://github.com/slawekradzyminski/test-secure-backend/blob/master/src/main/proto/awesome/inventory/v1/inventory.proto)
is the schema students can import into Postman instead of using grpcurl.
