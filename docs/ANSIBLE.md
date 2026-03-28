# Ansible

This repository uses Ansible for VPS bootstrap, deployment, and post-deploy verification.

## Source of Truth

Phase 2 moved Ansible off local shell env files and onto inventory plus Vault.

- Non-secret deployment defaults live in [main.yml](../ansible/inventory/group_vars/production/main.yml).
- The tracked template is `ansible/inventory/group_vars/production/vault.yml.example`.
- The real local secret file is `ansible/inventory/group_vars/production/vault.yml`.
- The local Vault password file is `ansible/.vault_pass` and is gitignored.
- The real local Vault file is gitignored and must not be committed.

## Layout

```text
ansible/
  ansible.cfg
  inventory/
    production.yml
    group_vars/
      production/
        main.yml
        vault.yml.example
  playbooks/
    bootstrap.yml
    deploy.yml
    verify.yml
  roles/
    base/
    docker/
    app/
    verify/
  requirements.yml
Makefile
```

## Commands

Install required collections:

```bash
make ansible-galaxy
```

Check host connectivity:

```bash
make ansible-ping
```

Open an SSH session using the same resolved values Ansible uses:

```bash
make ansible-ssh
```

Bootstrap the VPS:

```bash
make ansible-bootstrap
```

Deploy the stack:

```bash
make ansible-deploy
```

Run verification only:

```bash
make ansible-verify
```

Start SSH tunnels:

```bash
make ansible-tunnel-grafana
make ansible-tunnel-mailhog
make ansible-tunnel-all
```

Kill SSH tunnels:

```bash
make ansible-tunnel-kill-grafana
make ansible-tunnel-kill-mailhog
make ansible-tunnel-kill-all
```

Edit encrypted production vars:

```bash
make ansible-edit-vault
```

Initialize a local Vault file on a new machine:

```bash
cp ansible/inventory/group_vars/production/vault.yml.example \
  ansible/inventory/group_vars/production/vault.yml
cd ansible
ansible-vault encrypt inventory/group_vars/production/vault.yml --vault-password-file .vault_pass
```

## How Deploy Works

`deploy.yml` is the normal operational entrypoint.

It does two things in order:

1. Runs the `app` role to converge files and Docker Compose state in `/opt/awesome-localstack`.
2. Runs the `verify` role to make sure the deployed stack is actually reachable.

This is intentional. In this project, a deploy that leaves the gateway returning `502` is a failed deploy, not a successful deploy with a separate follow-up check.

## Patterns Used

### Convergent deploys

The Compose task uses convergent settings rather than forced recreation:

- `pull: missing`
- `recreate: auto`
- `remove_orphans: true`

That keeps repeated deploys idempotent when the server state already matches the repo.

### Verification as part of deploy

The `verify` role remains separate so it can still be run on demand, but it is also included in `deploy.yml`.

The role checks:

- `docker compose ps`
- `http://127.0.0.1/v3/api-docs`
- `http://127.0.0.1/mailhog/api/v2/messages`

### Readiness retries

The backend is a JVM service and can take time to bind port `4001` after containers are already reported as running.

For that reason, HTTP verification uses retries and delay rather than failing immediately on a temporary `502`.

### Split responsibilities by role

- `base`: baseline packages, app directory, SSH daemon hardening for key-only root login
- `docker`: Docker apt repository, engine, Compose plugin, daemon state
- `app`: file sync, runtime env rendering, Compose convergence
- `verify`: operational checks after deploy

## Vault Workflow

The local production Vault file stores values such as:

- `production_ssh_host`
- `production_ssh_port`
- `production_ssh_user`
- `production_ssh_key_path`
- `grafana_admin_password`

To rotate or update them:

```bash
make ansible-edit-vault
```

## Manual Usage

Run a playbook directly:

```bash
cd ansible
ansible-playbook playbooks/deploy.yml --vault-password-file .vault_pass
```

Run an ad hoc command:

```bash
cd ansible
ansible production -a 'docker compose -f /opt/awesome-localstack/docker-compose.server.yml ps' --vault-password-file .vault_pass
```

Resolve the SSH connection values Ansible uses:

```bash
cd ansible
./resolve-ssh-vars.sh
```

## Notes

- `verify.yml` is still useful when you want smoke checks without changing deployment state.
- `bootstrap.yml` is intended to be idempotent on an already-configured host.
- The old shell deployment path has been removed; use `make ansible-deploy`.
