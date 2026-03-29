# SSH server access

## Current source of truth

Ansible phase 2 moved deployment configuration to:

- [main.yml](../ansible/inventory/group_vars/production/main.yml)
- `ansible/inventory/group_vars/production/vault.yml.example`
- local gitignored `ansible/inventory/group_vars/production/vault.yml`

See [ANSIBLE.md](ANSIBLE.md) for the operational workflow.

## Recommended commands

Use Ansible-backed `make` targets for normal operations:

```bash
make ansible-ping
make ansible-ssh
make ansible-deploy
make ansible-verify
```

## Notes

For deployment, verification, SSH access, and tunnels, the source of truth is the Ansible inventory plus Vault.

Grafana runtime configuration also comes from Vault-backed Ansible vars.

## SSH tunnels for local browser access

The server profile binds Grafana and Mailhog UI only to `127.0.0.1` on the VPS. They are not public on the internet.

Use the Ansible-backed `make` targets to access them from your browser.

### Grafana only

```bash
make ansible-tunnel-grafana
```

Then open:

- `http://localhost:3000`

Keep that terminal open while you use Grafana.

### Mailhog UI only

```bash
make ansible-tunnel-mailhog
```

Then open:

- `http://localhost:8025`

### Grafana and Mailhog UI in one tunnel

```bash
make ansible-tunnel-all
```

Then open:

- `http://localhost:3000`
- `http://localhost:8025`

Kill helper targets:

```bash
make ansible-tunnel-kill-grafana
make ansible-tunnel-kill-mailhog
make ansible-tunnel-kill-all
```

## Backend logs on the server

For the deployed server stack in `/opt/awesome-localstack`, use `docker compose` on the host.

Open a shell on the server:

```bash
make ansible-ssh
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
docker compose -f docker-compose.server.yml exec gateway curl -sS http://backend:4001/actuator/health

# Mailhog API directly on the VPS loopback
curl -sS http://127.0.0.1:8025/api/v2/messages
```

Run these from your local machine:

```bash
curl -sS https://awesome.byst.re/v3/api-docs | jq '.servers'
curl -i https://awesome.byst.re/mailhog/api/v2/messages
```

For an authenticated public-safe email visibility check, sign in first and then call:

```bash
curl -sS https://awesome.byst.re/api/v1/users/me/email-events \
  -H "Authorization: Bearer <TOKEN>" | jq
```

## Debugging tips

- If the public domain returns `502`, check `docker compose -f docker-compose.server.yml ps` first. Most often the backend is still starting or was recreated during deploy.
- If backend is healthy but the public domain still fails, tail both `backend` and `gateway` logs together in two terminals. Gateway errors usually show `connect() failed (111: Connection refused)` when the backend is not ready yet.
- If nginx config changes do not seem to apply, recreate the gateway container. This repo bind-mounts a single nginx config file, and a plain `up -d` may leave the old mounted inode in place.
- If Swagger UI tries `http://` instead of `https://`, inspect `https://awesome.byst.re/v3/api-docs` and verify `.servers[0].url`.
- Public Mailhog routes are intentionally blocked. Inspect Mailhog through the VPS loopback `127.0.0.1:8025` or through the SSH tunnel targets instead.
- Postgres is intentionally not published on a host port in the server compose. Check it through Docker network access, not by expecting `localhost:5432` on the VPS.
- `make ansible-reset-demo-state` is destructive for the server Postgres volume. It recreates the bootstrap admin and public product catalog, but it clears orders, email events, and any ad hoc demo users.
