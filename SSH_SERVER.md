# SSH server access

## Environment variables

Store all SSH connection details in `.env`. Use `.env.example` as the template:

```env
SSH_HOST=example.host
SSH_PORT=22
SSH_USER=root
SSH_IPV6=::1
SSH_NODE=example-node
SSH_PASSWORD=example-password
```

`.env` is already ignored by git in this repository.

## Connect from terminal

Load the variables and connect with standard SSH:

```bash
set -a
source .env
set +a
ssh -p "$SSH_PORT" "$SSH_USER@$SSH_HOST"
```

If the server does not accept plain password auth, force `keyboard-interactive`:

```bash
set -a
source .env
set +a
ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no -p "$SSH_PORT" "$SSH_USER@$SSH_HOST"
```

## Quick connectivity check using `.env`

This verifies login non-interactively by reading all required values from `.env`:

```bash
expect <<'EOF'
set timeout 20
array set cfg {}
set fh [open ".env" r]
while {[gets $fh line] >= 0} {
  if {[regexp {^([A-Z0-9_]+)=(.*)$} $line -> key value]} {
    set cfg($key) $value
  }
}
close $fh

spawn ssh -o StrictHostKeyChecking=accept-new -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no -p $cfg(SSH_PORT) $cfg(SSH_USER)@$cfg(SSH_HOST) "whoami"
expect {
  -re ".*assword:.*" { send -- "$cfg(SSH_PASSWORD)\r"; exp_continue }
  -re "$cfg\\(SSH_USER\\)\r?\n" { puts "SSH connected successfully"; exit 0 }
  timeout { puts "SSH connection timed out"; exit 1 }
  eof { exit 1 }
}
EOF
```

## Notes

`SSH_IPV6` and `SSH_NODE` are stored in `.env` for reference, but they are not required for the standard SSH command above.

## Backend logs on the server

For the deployed server stack in `/opt/awesome-localstack`, use `docker compose` on the host.

Open a shell on the server:

```bash
set -a
source .env
set +a
ssh -o PreferredAuthentications=keyboard-interactive -o PubkeyAuthentication=no -p "$SSH_PORT" "$SSH_USER@$SSH_HOST"
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
