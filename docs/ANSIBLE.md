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
    deployment_silence/
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

It performs seven steps in order:

1. Runs the guarded `swap` role. It can converge a 1 GiB emergency swap file
   and low swappiness on capable hosts; it reports a tracked reason and makes no
   swap changes on the current MIKR.US LXC host.
2. Runs the `postgres_backup` role and creates the encrypted pre-deploy backup.
3. Creates 15-minute Alertmanager silences for the warning-level
   `PublicEndpointProbeFailed` alert and the backend, consumer,
   warehouse-service and payment-service `PrometheusTargetDown` warnings when the existing monitoring stack is
   reachable. The five-minute critical alerts remain active.
4. Runs the `app` role to reconcile the existing PostgreSQL role with the
   Vault-managed password, render the protected runtime environment, and
   converge files and Docker Compose state in `/opt/awesome-localstack`.
5. Runs the `verify` role to make sure the deployed stack is actually
   reachable.
6. Expires the warning silences immediately after verification succeeds. If a
   deploy fails first, the silences expire automatically after 15 minutes.
7. Runs the guarded `cleanup` role only after verification succeeds.

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
- every GraalVM native service runs with its expected `-Xmx` argument:
  `backend` `-Xmx384m`, `aitesters-backend` `-Xmx256m`, and `-Xmx64m` for
  `consumer`, `warehouse-service`, `aitesters-warehouse-service`,
  `payment-service` and `aitesters-payment-service`
- the `warehouse` and `payment` database roles of both databases own their
  schema, cannot read `public.orders` or `public.app_user`, cannot create in
  `public` and cannot use each other's schema
- the direct warehouse-service and payment-service health and OpenAPI routes,
  `/warehouse/v3/api-docs` and `/payment/v3/api-docs` through the gateway (both
  hosts), and `/api/v1/tracking/<unknown>` answering `404` from
  warehouse-service
- the `Production Resources` and `Production Availability & Safeguards`
  Grafana dashboards are mounted
- bootstrap admin sign-in succeeds
- authenticated `GET /api/v1/products` returns a non-empty catalog

### Readiness retries

The backends start in about a second as native images, but they wait for PostgreSQL and Flyway, and the gateway may briefly answer `502` while containers are recreated.

For that reason, HTTP verification uses retries and delay rather than failing immediately on a temporary `502`.

### Split responsibilities by role

- `base`: baseline packages, app directory, SSH daemon hardening for key-only root login
- `docker`: Docker apt repository, engine, Compose plugin, daemon state
- `swap`: guarded emergency-swap convergence; disabled on the current LXC host
  because the provider rejects `swapon`
- `postgres_backup`: encrypted backups, restore checks, and the pre-deploy backup
- `deployment_silence`: bounded suppression of planned warning-level public
  endpoint and backend/consumer scrape alerts; critical alerts are never silenced
- `app`: file sync, runtime env rendering, Compose convergence
- `verify`: operational checks after deploy
- `cleanup`: checksum- and age-guarded retirement of the legacy Artemis volume
  plus pruning of unused images older than the retention window

### PostgreSQL restore verification

The weekly checker restores the latest encrypted backup into a disposable
PostgreSQL container and requires at least one public table. Readiness and SQL
connections use TCP on `127.0.0.1`: the image's temporary initialization server
accepts Unix-socket connections before the permanent server starts. A socket
probe can therefore report readiness just before initialization shuts it down,
which caused the 2026-10-04 verification failure.

Run `python3 scripts/verify-postgres-restore.py` to verify this contract locally
with Docker. The check deliberately delays initialization, restores an encrypted
fixture, verifies its data, and removes the disposable container. CI runs it too.

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
- `postgres_password`
- `app_bootstrap_admin_enabled`
- `app_bootstrap_admin_username`
- `app_bootstrap_admin_password`
- `app_bootstrap_admin_email`
- `jwt_signing_key`, `aitesters_jwt_signing_key`
- `warehouse_service_token`, `aitesters_warehouse_service_token`
- `warehouse_postgres_password`, `aitesters_warehouse_postgres_password`,
  `aitesters_postgres_password`
- `payment_service_token`, `aitesters_payment_service_token`
- `payment_webhook_secret`, `aitesters_payment_webhook_secret`
- `payment_postgres_password`, `aitesters_payment_postgres_password`

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

## Stable and sandbox authentication isolation

Configure distinct `jwt_signing_key` and `aitesters_jwt_signing_key` values in
Ansible Vault: single-line base64 PKCS#8 RSA private keys of at least 2048 bits
(`openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 | openssl pkcs8
-topk8 -nocrypt -outform DER | base64 | tr -d '\n'`; OpenSSL 3 writes PKCS#1
for `genpkey -outform DER`, which the backend rejects). The backends sign access tokens with RS256 and publish
the public keys at `/internal/v1/jwks.json` for their warehouse-services.
Deployment renders `.env.runtime` for the stable backend and `.env.aitesters`
for the disposable backend. The latter receives the same required service
settings with its own signing key, and never inherits the stable runtime file. Both files are root-owned mode 0600 and ignored
by Git. Ansible rejects missing, malformed or equal signing keys and verifies that tokens
issued by one site return HTTP 401 at the other.

## warehouse-service secrets and image gate

Configure `warehouse_service_token` in Ansible Vault (at least 32 random
characters, for example `openssl rand -hex 32`).
It reaches the stable backend through `.env.runtime` and warehouse-service
through `.env.warehouse`, which contains only `WAREHOUSE_SERVICE_TOKEN` and
`SPRING_DATASOURCE_PASSWORD` (root-owned, mode 0600). warehouse-service
verifies access tokens with the backend's JWKS and connects as the `warehouse`
database role, whose password is `warehouse_postgres_password`
(`aitesters_warehouse_postgres_password` in the sandbox, each at least 16
characters and distinct from the superuser passwords). The one-shot
`postgres-roles` and `aitesters-postgres-roles` services run
`postgres/service-roles.sh` (which runs `postgres/service-role.sh` for the
`warehouse` and `payment` roles) with `.env.postgres-roles` /
`.env.aitesters-postgres-roles` (superuser and role passwords) before every
warehouse-service start: they create or update the role, hand it the
`warehouse` schema and its tables, and fail if it could read the backend's
`public` tables. Verification expects both one-shots to have exited 0 and
checks that the role owns `warehouse` and cannot read `public.orders` or
`public.app_user`. The aitesters sandbox pairs `aitesters-backend` with its own
`aitesters-warehouse-service`, both on `aitesters-postgres` (database
`aitesters`, warehouse schema `warehouse`): `.env.aitesters` carries
`aitesters_warehouse_service_token` and replaces the stable database password
with `aitesters_postgres_password`; `.env.aitesters-warehouse` /
`.env.aitesters-postgres` carry that token, the sandbox warehouse role password
and the sandbox superuser password. The nightly reset recreates the database,
`aitesters-postgres-roles`, the backend and warehouse-service with
`--renew-anon-volumes`, so the sandbox database starts empty and reseeds. Deployment fails unless both warehouse
services use a published `tag@sha256` (the VPS cannot build the native image);
set `warehouse_service_allow_unpinned_image=true` only for a deliberately
pre-loaded image. Verification checks the direct `warehouse-service:4003` and
`aitesters-warehouse-service:4003` health and OpenAPI routes, the aitesters
host's `/warehouse/v3/api-docs` and `/internal/` routes, the `-Xmx64m` argument
of every native image, the proxied `/warehouse/v3/api-docs` route, the `/internal/`
404 guard, and the `spring_warehouse_micrometer` scrape job.

## payment-service secrets and image gate

Add six values to Ansible Vault (see `vault.yml.example`):

| Key | Rule | Reaches |
| --- | --- | --- |
| `payment_service_token` | at least 32 characters (`openssl rand -hex 32`) | `.env.runtime` (backend) and `.env.payment` |
| `aitesters_payment_service_token` | at least 32 characters | `.env.aitesters` and `.env.aitesters-payment` |
| `payment_webhook_secret` | at least 32 characters | `.env.runtime` and `.env.payment` |
| `aitesters_payment_webhook_secret` | at least 32 characters | `.env.aitesters` and `.env.aitesters-payment` |
| `payment_postgres_password` | at least 16 characters | `.env.payment`, `.env.postgres-roles` |
| `aitesters_payment_postgres_password` | at least 16 characters | `.env.aitesters-payment`, `.env.aitesters-postgres-roles` |

The `app` role refuses to deploy unless the four tokens and webhook secrets
differ from each other and from both warehouse service tokens, and the six
database passwords (superusers, warehouse and payment roles of both databases)
are all distinct. `.env.payment` and `.env.aitesters-payment` (root-owned,
mode 0600) contain only `PAYMENT_SERVICE_TOKEN`, `PAYMENT_WEBHOOK_SECRET` and
`SPRING_DATASOURCE_PASSWORD`; payment-service verifies access tokens with its
backend's JWKS and holds no signing key. The backends reach payment-service at
`PAYMENT_BASE_URL` (`http://payment-service:4004`,
`http://aitesters-payment-service:4004`), set in Compose.

The one-shot `postgres-roles` services prepare the `payment` role and schema
next to `warehouse`, so the payment role password is required for both
one-shots. The nightly aitesters reset and `make ansible-reset-aitesters-state`
also recreate `aitesters-payment-service`, and the coordinated backend upgrade
stops both payment-services with the backends.

Deployment fails unless `payment-service` and `aitesters-payment-service` use
a published `tag@sha256`. Until payment-service 1.0.0 is published the server
Compose file carries the placeholder
`slawekradzyminski/payment-service:1.0.0@sha256:PENDING_PAYMENT_SERVICE_DIGEST`,
so the gate fails on purpose; set `payment_service_allow_unpinned_image=true`
only for a deliberately pre-loaded image. Verification adds the
`spring_payment_micrometer` scrape job, the public probe of
`https://awesome.byst.re/payment/v3/api-docs` (four public probes in total) and
the `-Xmx64m` heap of both payment-services.

## Memory budget

The VPS has about 4.25 GiB of RAM and no swap. Container limits are safety
ceilings and are deliberately overcommitted: the long-running services' limits
add up to about 5.8 GiB, while the last measured host had 2.8 GiB available
(9 November 2026, after the native-image migration).

This release adds two more 160 MiB containers, `payment-service` and
`aitesters-payment-service` (GraalVM native images with `-Xmx64m`, like the
warehouse-services, which measure 58 to 66 MiB each). Their limits add
320 MiB to the overcommitted total; the expected working set is about
120 to 140 MiB, which leaves roughly 2.6 GiB available. Measure
`MemAvailable` and the payment-services' working sets after the first deploy
and record them in `docs/CONTAINER_RELEASES.md`; if available memory drops
below 1.5 GiB, lower a limit (the `ContainerMemoryNearLimit` warnings show
which) before adding further services.

## Documentation wiki image

The `docs` service (the MkDocs wiki at `/docs/`, `mem_limit: 32m`) is the only
image built on the server. The `app` role copies `docs/` and `docs-site/` and
runs `docker compose build docs` before `docker compose up`; the image is
static files on the digest-pinned `nginx:1.31.3-trixie` base (shared with the
gateway), so no registry release or digest pin is needed for documentation
edits (`awesome-localstack/docs:local`, `pull_policy: build`, exempt from
`verify-image-pins.py` like other `:local` builds). The build needs outbound
access to PyPI and jsDelivr. `verify` checks `http://docs/docs/` from the
gateway container and `/docs/` on both hosts.
