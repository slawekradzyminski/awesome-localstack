# Optional native gRPC inventory listener

Backend 3.8.0 includes four admin-only inventory RPCs. All primary Compose
profiles pin this release. The override adds the listener to the lightweight
stack without rebuilding; it defaults to the same pinned backend image:

For a step-by-step classroom exercise, see the [gRPC training runbook](GRPC_TRAINING_RUNBOOK.md).

```bash
docker compose -f lightweight-docker-compose.yml -f docker-compose.grpc.yml config --quiet
docker compose -f lightweight-docker-compose.yml -f docker-compose.grpc.yml up -d
```

To turn the lightweight listener off again without tearing down the stack, run
`docker compose -f lightweight-docker-compose.yml up -d --force-recreate backend`.
Use `docker-compose.yml` instead for the full profile. The override defaults to
the same pinned backend image and preserves the base active profiles, adding
`graphql,grpc` and a loopback port. `GRPC_BACKEND_IMAGE` can select a candidate
image in a disposable compatibility run. No other service or image pin changes.

The native endpoint is `127.0.0.1:9091`. Change `GRPC_HOST_PORT` if that host port
is occupied; Prometheus remains on 9090. Inside the backend container, gRPC listens
on 9091. The host mapping is loopback-only, including when this override is merged
with the server file. There is no public gRPC route through nginx.

Reflection is off by default. Use the checked-in `.proto` with grpcurl or Postman.
Set `GRPC_REFLECTION_ENABLED=true` before starting the override if you need
training-time schema discovery; reflection and health require an admin JWT too.
Full and lightweight startup without this override does not activate the native
listener. The server profile explicitly enables it as described below.
GraphQL and GraphiQL remain enabled by default in the updated backend.

For examples, status codes, presence semantics, deadlines, and idempotent retry
rules, see [backend gRPC documentation](https://github.com/slawekradzyminski/test-secure-backend/blob/master/docs/GRPC.md).
For verification evidence, see [gRPC verification](GRPC_VERIFICATION.md).

## Server deployment and SSH access

The server profile enables native gRPC explicitly for both backend instances.
The stable inventory listener is published on server loopback `127.0.0.1:9091`;
the disposable `aitesters` listener uses `127.0.0.1:9092`. Neither listener is a
public nginx endpoint. Reflection remains disabled and every inventory RPC
requires the corresponding site's admin JWT.

Create a tunnel using the existing Vault-managed SSH settings:

```bash
eval "$(cd ansible && ./resolve-ssh-vars.sh)"
ssh -o StrictHostKeyChecking=accept-new -N \
  -L 14991:127.0.0.1:9091 -L 14992:127.0.0.1:9092 \
  -p "$SSH_PORT" -i "$SSH_KEY_PATH" "$SSH_USER@$SSH_HOST"
```

Point grpcurl at `127.0.0.1:14991` for stable data or `127.0.0.1:14992` for
sandbox data. The tunnel supplies encryption for the plaintext native listener.
Use the matching site's JWT and, for traffic capture, its frontend traffic
session ID. See the [protocol lab](PROTOCOL_TESTING_LAB.md). The standalone
full/lightweight profiles still require the opt-in gRPC override.
