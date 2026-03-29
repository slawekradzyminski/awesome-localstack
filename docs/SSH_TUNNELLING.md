# SSH Tunnelling Guide

This file explains how to access private server-only UIs through SSH tunnels.

The recommended path is to use the Ansible-backed `make` targets. They resolve SSH connection details from the Vault-backed inventory.

Current intended private UIs:

- Grafana on remote `127.0.0.1:3000`
- Mailhog UI and API on remote `127.0.0.1:8025`

## Recommended usage

Grafana only:

```bash
make ansible-tunnel-grafana
```

Mailhog only:

```bash
make ansible-tunnel-mailhog
```

Grafana and Mailhog together:

```bash
make ansible-tunnel-all
```

Then open:

- `http://localhost:3000`
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

Kill Grafana-only tunnels:

```bash
make ansible-tunnel-kill-grafana
```

Kill Mailhog-only tunnels:

```bash
make ansible-tunnel-kill-mailhog
```

Kill the combined Grafana + Mailhog tunnel:

```bash
make ansible-tunnel-kill-all
```

### Raw process kill examples

Kill Grafana-only tunnels:

```bash
pkill -f 'ssh -N .*3000:127.0.0.1:3000'
```

Kill Mailhog-only tunnels:

```bash
pkill -f 'ssh -N .*8025:127.0.0.1:8025'
```

Kill any supported tunnel:

```bash
pkill -f 'ssh -N .*3000:127.0.0.1:3000|ssh -N .*8025:127.0.0.1:8025'
```

## How to verify the tunnel is active

Check local listeners:

```bash
lsof -iTCP:3000 -sTCP:LISTEN
lsof -iTCP:8025 -sTCP:LISTEN
```

Or just open:

- `http://localhost:3000`
- `http://localhost:8025`

If the tunnel is down, the browser will fail to connect.
