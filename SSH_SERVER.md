# SSH server access

## Environment variables

Store all SSH connection details in `.env`. Use `.env.example` as the template:

```env
SSH_HOST=example.host
SSH_PORT=22
SSH_USER=root
SSH_KEY_PATH=/absolute/path/to/private-key
SSH_IPV6=::1
SSH_NODE=example-node
GRAFANA_ADMIN_PASSWORD=change-this-to-a-strong-value
```

`.env` is already ignored by git in this repository.

## Connect from terminal

Load the variables and connect with standard SSH:

```bash
set -a
source .env
set +a
ssh -p "$SSH_PORT" -i "$SSH_KEY_PATH" "$SSH_USER@$SSH_HOST"
```

Equivalent explicit form:

```bash
ssh -p "$SSH_PORT" -i "$SSH_KEY_PATH" "$SSH_USER@$SSH_HOST"
```

## Quick connectivity check using `.env`

This verifies login by reading all required values from `.env`:

```bash
set -a
source .env
set +a
ssh -o StrictHostKeyChecking=accept-new -p "$SSH_PORT" -i "$SSH_KEY_PATH" "$SSH_USER@$SSH_HOST" "whoami"
```

## Notes

`SSH_HOST`, `SSH_PORT`, and `SSH_USER` stay in `.env` so the real server details are not hardcoded into commands in this repository.

`SSH_KEY_PATH` should point to your private key file and is read directly from `.env`.

`SSH_IPV6` and `SSH_NODE` are stored in `.env` for reference, but they are not required for the standard SSH command above.

`GRAFANA_ADMIN_PASSWORD` is optional for SSH itself, but recommended if you deploy Grafana in the server profile. `deploy-server.sh` copies only this runtime secret into `.env.runtime` on the server, not the SSH credentials.

## SSH tunnels for local browser access

The server profile binds Grafana and Mailhog UI only to `127.0.0.1` on the VPS. They are not public on the internet.

Use SSH tunnels to access them from your browser.

### Grafana only

```bash
set -a
source .env
set +a
ssh -N -L 3000:127.0.0.1:3000 -p "$SSH_PORT" -i "$SSH_KEY_PATH" "$SSH_USER@$SSH_HOST"
```

Then open:

- `http://localhost:3000`

Keep that terminal open while you use Grafana.

### Mailhog UI only

```bash
set -a
source .env
set +a
ssh -N -L 8025:127.0.0.1:8025 -p "$SSH_PORT" -i "$SSH_KEY_PATH" "$SSH_USER@$SSH_HOST"
```

Then open:

- `http://localhost:8025`

### Grafana and Mailhog UI in one tunnel

```bash
set -a
source .env
set +a
ssh -N \
  -L 3000:127.0.0.1:3000 \
  -L 8025:127.0.0.1:8025 \
  -p "$SSH_PORT" \
  -i "$SSH_KEY_PATH" \
  "$SSH_USER@$SSH_HOST"
```

Then open:

- `http://localhost:3000`
- `http://localhost:8025`

## Backend logs on the server

For the deployed server stack in `/opt/awesome-localstack`, use `docker compose` on the host.

Open a shell on the server:

```bash
set -a
source .env
set +a
ssh -p "$SSH_PORT" -i "$SSH_KEY_PATH" "$SSH_USER@$SSH_HOST"
```

Then follow backend logs live:

```bash
cd /opt/awesome-localstack
docker compose -f docker-compose.server.yml logs -f backend
```

Useful variants:

```bash
# Last 200 backend log lines, then keep following
docker compose -f docker-compose.server.yml logs --tail=200 -f backend

# Follow gateway logs
docker compose -f docker-compose.server.yml logs --tail=200 -f gateway

# Follow consumer logs
docker compose -f docker-compose.server.yml logs --tail=200 -f consumer

# Show service status
docker compose -f docker-compose.server.yml ps
```

## Fast production checks

Run these on the server:

```bash
cd /opt/awesome-localstack

# Backend through gateway
curl -sS http://127.0.0.1/v3/api-docs | jq '.servers'

# Backend direct inside Docker network
docker exec awesome-localstack-gateway-1 curl -sS http://backend:4001/actuator/health

# Mailhog API through gateway
curl -sS http://127.0.0.1/mailhog/api/v2/messages
```

Run these from your local machine:

```bash
curl -sS https://awesome.byst.re/v3/api-docs | jq '.servers'
curl -sS https://awesome.byst.re/mailhog/api/v2/messages
curl -sS -X POST https://awesome.byst.re/api/v1/users/signin \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}'
```

## Debugging tips

- If the public domain returns `502`, check `docker compose -f docker-compose.server.yml ps` first. Most often the backend is still starting or was recreated during deploy.
- If backend is healthy but the public domain still fails, tail both `backend` and `gateway` logs together in two terminals. Gateway errors usually show `connect() failed (111: Connection refused)` when the backend is not ready yet.
- If nginx config changes do not seem to apply, recreate the gateway container. This repo bind-mounts a single nginx config file, and a plain `up -d` may leave the old mounted inode in place.
- If Swagger UI tries `http://` instead of `https://`, inspect `https://awesome.byst.re/v3/api-docs` and verify `.servers[0].url`.
- For Mailhog, prefer `GET /mailhog/api/v2/messages`. `HEAD` may return a misleading non-200 even when the API works.
- Postgres and Mailhog are intentionally not published on host ports in the server compose. Check them through Docker network access or gateway routes, not by expecting `localhost:5432` or `localhost:8025` on the VPS.
