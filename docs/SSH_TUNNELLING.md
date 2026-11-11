# SSH Tunnelling Guide

This file explains how to access private server-only UIs through SSH tunnels.

The recommended path is to use the Ansible-backed `make` targets. They resolve SSH connection details from the Vault-backed inventory.

Current intended private UIs:

- Prometheus on remote `127.0.0.1:9090` (production has no Grafana since lean monitoring phase A)
- Mailpit UI and API on remote `127.0.0.1:8025`

Mailpit is private on purpose. The public demo uses application-owned endpoints such as `GET /api/v1/users/me/email-events` instead of exposing the inbox API on the public hostname.

## Recommended usage

Prometheus only:

```bash
make ansible-tunnel-prometheus
```

Mailpit only:

```bash
make ansible-tunnel-mailpit
```

Prometheus and Mailpit together:

```bash
make ansible-tunnel-all
```

Then open:

- `http://localhost:9090`
- `http://localhost:8025`

## How to stop the tunnel

### If the tunnel is running in the current terminal

Press:

- `Ctrl-C`

That is the normal and preferred way to stop it.

### If the tunnel is still running in another terminal

Find it:

```bash
ps aux | grep 'ssh -N'
```

Kill a specific tunnel process:

```bash
kill <PID>
```

### Make targets

Kill Prometheus-only tunnels:

```bash
make ansible-tunnel-kill-prometheus
```

Kill Mailpit-only tunnels:

```bash
make ansible-tunnel-kill-mailpit
```

Kill the combined Prometheus + Mailpit tunnel:

```bash
make ansible-tunnel-kill-all
```

### Raw process kill examples

Kill Prometheus-only tunnels:

```bash
pkill -f 'ssh -N .*9090:127.0.0.1:9090'
```

Kill Mailpit-only tunnels:

```bash
pkill -f 'ssh -N .*8025:127.0.0.1:8025'
```

Kill any supported tunnel:

```bash
pkill -f 'ssh -N .*9090:127.0.0.1:9090|ssh -N .*8025:127.0.0.1:8025'
```

## How to verify the tunnel is active

Check local listeners:

```bash
lsof -iTCP:9090 -sTCP:LISTEN
lsof -iTCP:8025 -sTCP:LISTEN
```

Or just open:

- `http://localhost:9090`
- `http://localhost:8025`

If the tunnel is down, the browser will fail to connect.
