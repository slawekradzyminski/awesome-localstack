# SSH Tunnelling Guide

This file explains how to access private server-only UIs through SSH tunnels.

Current intended private UIs:

- Grafana on remote `127.0.0.1:3000`
- Mailhog UI on remote `127.0.0.1:8025`

## Prerequisites

Store connection details in `.env`:

```env
SSH_HOST=example.host
SSH_PORT=22
SSH_USER=example-user
SSH_KEY_PATH=/absolute/path/to/private-key
GRAFANA_ADMIN_PASSWORD=choose-a-strong-password
```

Load them into your shell before running the commands below:

```bash
set -a
source .env
set +a
```

## Start a tunnel

### Grafana only

```bash
ssh -N \
  -L 3000:127.0.0.1:3000 \
  -p "$SSH_PORT" \
  -i "$SSH_KEY_PATH" \
  "$SSH_USER@$SSH_HOST"
```

Then open:

- `http://localhost:3000`

### Mailhog UI only

```bash
ssh -N \
  -L 8025:127.0.0.1:8025 \
  -p "$SSH_PORT" \
  -i "$SSH_KEY_PATH" \
  "$SSH_USER@$SSH_HOST"
```

Then open:

- `http://localhost:8025`

### Grafana and Mailhog in one SSH session

```bash
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

### Quick kill examples

Kill Grafana-only tunnels:

```bash
pkill -f 'ssh -N .*3000:127.0.0.1:3000'
```

Kill Mailhog-only tunnels:

```bash
pkill -f 'ssh -N .*8025:127.0.0.1:8025'
```

Kill the combined Grafana + Mailhog tunnel:

```bash
pkill -f 'ssh -N .*3000:127.0.0.1:3000.*8025:127.0.0.1:8025'
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
