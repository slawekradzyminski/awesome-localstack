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

The server profile binds Grafana and Mailpit UI only to `127.0.0.1` on the VPS. They are not public on the internet.

Use the Ansible-backed `make` targets to access them from your browser.

### Grafana only

```bash
make ansible-tunnel-grafana
```

Then open:

- `http://localhost:3000`
- direct safeguards dashboard:
  `http://localhost:3000/d/awesome-prod-safeguards/production-availability-safeguards?orgId=1`

Keep that terminal open while you use Grafana.

The server profile provisions:

- **Production Resources** for host memory and pressure, disk capacity, CPU,
  per-container memory and CPU, JVM heap, load, and Prometheus target health;
- **Production Availability & Safeguards** for public HTTPS status and latency,
  TLS lifetime, emergency swap use, paging, and memory PSI.

Alertmanager is not published on the VPS host. It receives Prometheus alerts
through the private Docker network and sends warning, critical, and resolved
notifications to the Telegram chat configured in Ansible Vault.

The HTTPS checks originate from the VPS through public DNS. They cover the
public gateway and certificate, but not a complete VPS or provider-network
failure. That final failure mode requires a separate off-server monitor.

### Phase 4/5 alert response

For `PublicEndpointProbeFailedCritical`:

1. Check both URLs from a separate network or phone, because the alerting probe
   originates on the VPS.
2. Check `docker compose -f docker-compose.server.yml ps` and the `edge`,
   `gateway`, and `backend` logs.
3. Compare the direct `http://127.0.0.1` route with the public HTTPS route to
   isolate application, proxy, DNS, and TLS failures.
4. Keep the alert active until both `probe_success` series return `1`.

For `PublicEndpointTLSExpiringCritical`, inspect the certificate served for
`awesome.byst.re`, repair or renew it at the public TLS edge, and confirm that
the TLS-lifetime panel rises above 21 days.

`HostSwapUsageCritical` and `HostSwapThrashing` can fire only on a future
swap-capable host. Treat them as memory-exhaustion incidents: identify the
growing container, preserve logs, stop only a pre-approved non-critical
workload if necessary, and increase capacity if the pressure is sustained.
Never automatically stop PostgreSQL or the main backend. On the current LXC
host, use the memory-availability and PSI alerts because provider-level swap is
unavailable.

### Mailpit UI only

```bash
make ansible-tunnel-mailpit
```

Then open:

- `http://localhost:8025`

### Grafana and Mailpit UI in one tunnel

```bash
make ansible-tunnel-all
```

Then open:

- `http://localhost:3000`
- `http://localhost:8025`

Kill helper targets:

```bash
make ansible-tunnel-kill-grafana
make ansible-tunnel-kill-mailpit
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

# Verify private monitoring endpoints through the Docker network
docker compose -f docker-compose.server.yml exec gateway curl -fsS -o /dev/null http://node-exporter:9100/metrics
docker compose -f docker-compose.server.yml exec gateway curl -fsS -o /dev/null http://cadvisor:8080/metrics
docker compose -f docker-compose.server.yml exec gateway curl -fsS http://prometheus:9090/-/ready
docker compose -f docker-compose.server.yml exec gateway curl -fsS http://alertmanager:9093/-/ready
docker compose -f docker-compose.server.yml exec gateway curl -fsS http://blackbox-exporter:9115/-/healthy
docker compose -f docker-compose.server.yml exec gateway curl -fsS -G \
  --data-urlencode 'query=probe_success{job="public_https"}' \
  http://prometheus:9090/api/v1/query
swapon --show
sysctl vm.swappiness
```

## Fast production checks

Run these on the server:

```bash
cd /opt/awesome-localstack

# Backend through gateway
curl -sS http://127.0.0.1/v3/api-docs | jq '.servers'

# Backend direct inside Docker network
docker compose -f docker-compose.server.yml exec gateway curl -sS http://backend:4001/actuator/health

# Mailpit API directly on the VPS loopback
curl -sS http://127.0.0.1:8025/api/v1/messages
```

Run these from your local machine:

```bash
curl -sS https://awesome.byst.re/v3/api-docs | jq '.servers'
curl -i https://awesome.byst.re/mailpit/api/v1/messages
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
- Public Mailpit routes are intentionally blocked. Inspect Mailpit through the VPS loopback `127.0.0.1:8025` or through the SSH tunnel targets instead.
- Postgres is intentionally not published on a host port in the server compose. Check it through Docker network access, not by expecting `localhost:5432` on the VPS.
- `make ansible-reset-demo-state` is destructive for the server Postgres volume. It recreates the bootstrap admin and public product catalog, but it clears orders, email events, and any ad hoc demo users.
