# Troubleshooting

## Quick table

| Symptom | Likely cause | Check / fix |
| --- | --- | --- |
| `502 Bad Gateway` on every page | Backend still starting, or the gateway cached an old container address | `docker compose ... ps`; wait for `healthy`; recreate `gateway` |
| `502` only on warehouse, payment or `/docs/` paths | That service is down or restarting (the gateway resolves it per request) | `docker compose ... logs warehouse-service payment-service docs` |
| `503 {"message":"Backend unavailable"}` from warehouse or payment paths | The service is up but cannot reach the backend, or the service token is wrong | Compare `WAREHOUSE_SERVICE_TOKEN` / `PAYMENT_SERVICE_TOKEN` on both sides |
| `401` from warehouse/payment with a token that works on the backend | Token signed by a key the service cannot fetch, or an old token after a backend restart (ephemeral key) | Sign in again; check the service can reach `/internal/v1/jwks.json` |
| Order stays `PENDING` although the payment is `CAPTURED` | Result notification rejected (signature or secret mismatch) or backend down — the outbox retries | payment-service logs; `PAYMENT_WEBHOOK_SECRET` must match on both sides |
| warehouse-service or payment-service restarts at start | `postgres-roles` failed or the role password differs | `docker compose ... logs postgres-roles` |
| `port is already allocated` | Another profile (or tool) uses 8081, 8082 or 11434 | Stop the other profile first |
| Images missing in the shop | Wrong origin; images come from the gateway | Open `http://localhost:8081/images/iphone.png` |
| Swagger "Try it out" calls the wrong host | `servers[0].url` in `/v3/api-docs` | Use the gateway URL, not the service port |
| nginx changes not applied | The gateway still runs the old config | `docker compose ... up -d --force-recreate gateway` |
| SSO login fails | Keycloak not ready or realm not imported | `docker compose ... logs keycloak`; see [SSO flow](../reference/SSO_FLOW.md#troubleshooting) |
| No email arrives (full profile) | ActiveMQ or consumer down; the backend retries for ~15 minutes | Mailpit `:8025`, `GET /api/v1/users/me/email-events`, consumer logs |

## TOTP codes rejected locally (Docker VM clock drift)

TOTP accepts the current 30-second step and one adjacent step, so the
backend's clock may differ from your phone's by at most about 30–60 seconds.
On macOS and Windows, containers use the Docker Desktop VM's clock, which can
drift after the laptop sleeps. Symptom: freshly generated codes fail with
`401` at `/api/v1/users/signin/2fa` or `/2fa/confirm`, while the same account
works in production.

```bash
date -u; docker run --rm alpine:3 date -u     # compare the two clocks
```

If they differ by more than a few seconds, restart Docker Desktop (which
resynchronises the VM clock) and recreate the stack.

## Docker CLI hangs on macOS (credential helper)

If every `docker` command that talks to a registry (`pull`, `compose up`,
`buildx imagetools inspect`) hangs, the Docker Desktop credential helper is
usually stuck. Work around it with a temporary, empty Docker config that still
sees the CLI plugins:

```bash
export DOCKER_CONFIG="$(mktemp -d)"
echo '{}' > "$DOCKER_CONFIG/config.json"
ln -s ~/.docker/cli-plugins "$DOCKER_CONFIG/cli-plugins"
export DOCKER_HOST=unix://$HOME/.docker/run/docker.sock
docker compose -f lightweight-docker-compose.yml up -d
```

Anonymous pulls from Docker Hub work this way; registries that need a login do
not.

## Profiles confused after switching

Each profile has a fixed project name (`awesome-light`, `awesome-full-native`,
`awesome-server`), so orphans should not appear. If an interrupted run left
containers behind, `docker compose -f <file> down --remove-orphans` is the
fallback.

## Useful logs

```bash
docker compose -f lightweight-docker-compose.yml logs -f backend warehouse-service payment-service gateway
docker compose logs -f consumer activemq          # full profile
docker compose -f docker-compose.server.yml logs --tail=200 -f backend   # on the VPS
```

Every log line of one request, across all services: take its `X-Request-Id`
response header and follow [Tracing a request](tracing.md).

More symptoms: [Student guide — how to read failures](../reference/STUDENT_GUIDE.md#how-to-read-failures).
