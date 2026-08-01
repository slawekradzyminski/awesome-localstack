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
    swap/
    postgres_backup/
    app/
    verify/
    cleanup/
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

Run the guarded retention cleanup independently:

```bash
make ansible-cleanup
```

Reset the public demo data store and redeploy from a clean baseline:

```bash
make ansible-reset-demo-state
```

Start SSH tunnels:

```bash
make ansible-tunnel-grafana
make ansible-tunnel-mailpit
make ansible-tunnel-all
```

Kill SSH tunnels:

```bash
make ansible-tunnel-kill-grafana
make ansible-tunnel-kill-mailpit
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

It performs five steps in order:

1. Runs the guarded `swap` role. It can converge a 1 GiB emergency swap file
   and low swappiness on capable hosts; it reports a tracked reason and makes no
   swap changes on the current MIKR.US LXC host.
2. Runs the `postgres_backup` role and creates the encrypted pre-deploy backup.
3. Runs the `app` role to converge files and Docker Compose state in
   `/opt/awesome-localstack`.
4. Runs the `verify` role to make sure the deployed stack is actually
   reachable.
5. Runs the guarded `cleanup` role only after verification succeeds.

This is intentional. In this project, a deploy that leaves the gateway returning `502` is a failed deploy, not a successful deploy with a separate follow-up check.

`reset-demo-state.yml` is the destructive recovery path for the public demo host. It:

1. Stops the deployed stack.
2. Deletes the named Postgres volume for the server profile.
3. Runs the normal `app` and `verify` roles to recreate the stack from a clean baseline.

Because `mailpit` is recreated as part of the stack restart, its in-memory inbox is cleared too.

## Patterns Used

### Convergent deploys

The Compose task uses convergent settings rather than forced recreation:

- `pull: missing`
- `recreate: auto`
- `remove_orphans: true`

That keeps repeated deploys idempotent when the server state already matches the repo.

### Artemis 2.55 volume migration

The official `apache/artemis` image uses the explicit `activemq-data` volume.
The retired `apache/activemq-artemis` image created an anonymous instance
volume whose launch scripts refer to the old distribution layout and cannot be
reused by Artemis 2.55. Before the first deployment of Artemis 2.55, drain or
export pending messages and retain a backup of the anonymous volume. The first
convergent deployment creates the new named volume; do not delete the old
anonymous volume until the Artemis-to-consumer delivery check has passed.

### Verification as part of deploy

The `verify` role remains separate so it can still be run on demand, but it is also included in `deploy.yml`.

The role checks:

- `docker compose ps`
- every expected service is running the exact image ID resolved from the
  reviewed immutable Compose reference
- an Artemis message is consumed and delivered to Mailpit as a uniquely named
  email
- `http://127.0.0.1/login`
- `http://127.0.0.1/v3/api-docs`
- `http://127.0.0.1/images/iphone.png`
- `http://127.0.0.1/mailpit/api/v1/messages` returns `404`
- `http://127.0.0.1/mailpit/` returns `404`
- private Node Exporter, cAdvisor, Blackbox Exporter, Prometheus, and
  Alertmanager endpoints are reachable
- all expected Prometheus scrape jobs are healthy
- both public Blackbox probes currently succeed
- the emergency swap file and swappiness when `swap_enabled` is true
- the main backend and consumer expose bounded JVM maximum heaps
- the `Production Resources` and `Production Availability & Safeguards`
  Grafana dashboards are mounted
- bootstrap admin sign-in succeeds
- authenticated `GET /api/v1/products` returns a non-empty catalog

### Readiness retries

The backend is a JVM service and can take time to bind port `4001` after containers are already reported as running.

For that reason, HTTP verification uses retries and delay rather than failing immediately on a temporary `502`.

### Split responsibilities by role

- `base`: baseline packages, app directory, SSH daemon hardening for key-only root login
- `docker`: Docker apt repository, engine, Compose plugin, daemon state
- `swap`: guarded emergency-swap convergence; disabled on the current LXC host
  because the provider rejects `swapon`
- `postgres_backup`: encrypted backups, restore checks, and the pre-deploy backup
- `app`: file sync, runtime env rendering, Compose convergence
- `verify`: operational checks after deploy
- `cleanup`: checksum- and age-guarded retirement of the legacy Artemis volume
  plus pruning of unused images older than the retention window

### Retention-based container cleanup

The cleanup role installs a daily systemd timer and also runs once after a
successful deployment verification. The production retention window is 30
days. It removes only unused images older than that window.

The retired Artemis anonymous volume has an additional guard: the exact
encrypted backup and its checksum sidecar must exist and verify successfully,
the backup must be at least 30 days old, and no container may still reference
the volume. Until every condition passes, the volume is retained. The encrypted
backup is not deleted by this role.

## Vault Workflow

The local production Vault file stores values such as:

- `production_ssh_host`
- `production_ssh_port`
- `production_ssh_user`
- `production_ssh_key_path`
- `grafana_admin_password`
- `alertmanager_telegram_bot_token`
- `alertmanager_telegram_chat_id`
- `artemis_username`
- `artemis_password`
- `app_bootstrap_admin_enabled`
- `app_bootstrap_admin_username`
- `app_bootstrap_admin_password`
- `app_bootstrap_admin_email`

`APP_BOOTSTRAP_PRODUCTS_ENABLED` is tracked in `production/main.yml` rather than Vault so a clean reset recreates the public-safe catalog automatically.

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
