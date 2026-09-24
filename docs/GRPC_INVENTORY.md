# Optional native gRPC inventory listener

Backend 3.8.0 includes four admin-only inventory RPCs. All primary Compose
profiles now pin this release; use the override below to enable the listener
for the full or lightweight profile.

Build a local image from the backend repository, then opt into the override:

```bash
docker build -t awesome-backend:grpc-local ../test-secure-backend
GRPC_BACKEND_IMAGE=awesome-backend:grpc-local \
  docker compose -f lightweight-docker-compose.yml -f docker-compose.grpc.yml config --quiet
GRPC_BACKEND_IMAGE=awesome-backend:grpc-local \
  docker compose -f lightweight-docker-compose.yml -f docker-compose.grpc.yml up -d
```

Use `docker-compose.yml` instead for the full profile. The override preserves the
base active profiles and adds `graphql,grpc` to the included profiles. Other
services and deployment pins are unchanged. It requires an explicit backend image
so an older image is not mistaken for an implementation of this feature.

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
rules, see [backend gRPC documentation](../../test-secure-backend/docs/GRPC.md).
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
