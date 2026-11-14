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
    watchdog/
    postgres_backup/
    deployment_silence/
    backend_upgrade/      # main.yml: quiesce; recover.yml: restart after an early failure
    app/                  # prepare.yml: no service touched; converge.yml: containers
    verify/
    cleanup/
  tests/
    asset-mirror.yml      # driven by scripts/verify-asset-mirror.py
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
make ansible-deploy-backend-upgrade   # backend version changed: quiesce, quiesced backup, migrate
```

Both targets (and `make ansible-reset-demo-state`) first run
`make deploy-preflight` on the laptop: `docker compose -f
docker-compose.server.yml config --quiet` and the docs image build with its
`mkdocs build --strict` (`python3 scripts/release-train.py preflight`). A broken
docs tree or Compose file stops there, before Ansible connects.
`scripts/release-train.py deploy` runs the same preflight itself and calls the
target with `SKIP_DEPLOY_PREFLIGHT=1`.

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
make ansible-tunnel-prometheus
make ansible-tunnel-mailpit
make ansible-tunnel-all
```

Kill SSH tunnels:

```bash
make ansible-tunnel-kill-prometheus
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

`deploy.yml` is the normal operational entrypoint. Nothing that can fail for
a reason unrelated to the database migration runs after a service is stopped.

It performs these steps in order:

1. Runs the guarded `swap` role. It can converge a 1 GiB emergency swap file
   and low swappiness on capable hosts; it reports a tracked reason and makes no
   swap changes on the current MIKR.US LXC host.
2. Runs the `watchdog` role: installs the host watchdog script, its
   configuration, the one-minute `awesome-watchdog.timer` and the
   `awesome-watchdog-notify@.service` template the backup units use as
   `OnFailure=` (see [the lean monitoring plan](PRODUCTION_MONITORING_PLAN.md#lean-monitoring-phases-a-b-and-c)).
3. Runs the `postgres_backup` role and creates the encrypted pre-deploy backup.
4. **Prepares the release while the previous release still serves traffic**
   (`app` role, `prepare.yml`): validates the Vault keys and image gates,
   copies the Compose file, mirrors the asset directories (copy, then prune
   files the repository tracked and has since deleted; see
   [Asset directory mirror](#asset-directory-mirror)), renders the runtime
   `.env*` files and Alertmanager secrets, validates the result with
   `docker compose config --quiet`, pulls every missing image and builds the
   docs image (`mkdocs build --strict`). Running containers keep their old
   configuration: env files and single-file mounts are read when a container
   is created. A failure here stops the deploy with every service running.
5. Pauses the watchdog's container checks for 15 minutes and creates 15-minute
   Alertmanager silences for the warning-level
   `PublicEndpointProbeFailed` alert and the backend, consumer,
   warehouse-service and payment-service `PrometheusTargetDown` warnings when the existing monitoring stack is
   reachable. The five-minute critical alerts and the watchdog's OOM, disk,
   memory and backup checks remain active.
6. With `backend_upgrade_quiesce=true` (`make ansible-deploy-backend-upgrade`),
   runs the `backend_upgrade` role: pulls the reviewed backend, records the
   running backend, warehouse-service and payment-service containers, stops
   them and takes the quiesced encrypted backup (no writes after it).
7. Converges the containers (`app` role, `converge.yml`): reconciles the
   PostgreSQL role password with Vault, runs `docker compose up` (no build:
   the docs image is already built), restarts Prometheus or Alertmanager when
   their files changed, and recreates `gateway` and `edge`.
   Steps 6 and 7 run in one block whose `rescue` handles a failure: see
   [Recovering from a failed deploy](#recovering-from-a-failed-deploy).
8. Runs the `verify` role to make sure the deployed stack is actually
   reachable.
9. Expires the warning silences and resumes the watchdog immediately after
   verification succeeds. If a deploy fails first, both expire automatically
   after 15 minutes.
10. Runs the guarded `cleanup` role only after verification succeeds.

This is intentional. In this project, a deploy that leaves the gateway returning `502` is a failed deploy, not a successful deploy with a separate follow-up check.

`reset-demo-state.yml` is the destructive recovery path for the public demo host. It:

1. Stops the deployed stack.
2. Deletes the named Postgres volume for the server profile.
3. Runs the normal `app` and `verify` roles to recreate the stack from a clean baseline.

Because `mailpit` is recreated as part of the stack restart, its in-memory inbox is cleared too.

## Recovering from a failed deploy

The play ends with a message naming the failed task and what it did:

| Failed in | State | What to do |
| --- | --- | --- |
| Local preflight (`make deploy-preflight`) | Nothing was deployed. | Fix the Compose file or the docs (`mkdocs build --strict` names the page), commit, rerun. |
| Steps 1 to 5 (backup, prepare, silence) | No service was stopped; the previous release serves traffic. The server may hold the new files and env files, which running containers ignore. | Fix the cause and rerun the same make target. |
| Step 6 or 7 before `docker compose up` (quiesced backup, password reconciliation) | The rescue restarts the exact backend, warehouse-service and payment-service containers it stopped and waits until they are healthy; no migration ran. | Check the message's container states, fix the cause, rerun `make ansible-deploy-backend-upgrade`. |
| Step 7 from `docker compose up` on, or `verify` | The new release started; migrations may have run. The old backends are **not** restarted (their binaries may not accept the migrated schema). | Fix the cause and rerun the same make target; the play converges idempotently. If the new backend cannot run, roll back: re-pin the previous release and restore the quiesced backup ([Production backups](PRODUCTION_BACKUPS.md)). |

Silences and the watchdog pause expire after 15 minutes on their own; after
that a still-broken stack alerts normally. Check the state with
`make ansible-verify` or `docker compose -f docker-compose.server.yml ps` over
`make ansible-ssh`. Do not delete deployed files by hand in
`/opt/awesome-localstack`: the next run removes files the repository tracked
and deleted, and keeps (and lists) files git never tracked there.

## Patterns Used

### Asset directory mirror

The `app_copy_paths` directories (`security`, `postgres`, `nginx`,
`prometheus`, `alertmanager`, `blackbox`, `images`, `branding`, `docs`,
`docs-site`) mirror the checkout (`roles/app/tasks/assets.yml`):
`ansible.builtin.copy` uploads them (root-owned, modes preserved), then the
prune deletes only what Ansible could have put there. A deployed path is
deleted when it is

1. absent from the checkout, **and**
2. tracked in this repository's git history under the same path
   (`git log --all --no-renames --name-only -- <dirs>` on the laptop), **and**
3. not under `app_copy_prune_excludes` (role default: `alertmanager/secrets`,
   the rendered Telegram credentials).

A directory is deleted only when it held tracked files and nothing untracked
remains below it. Everything else the checkout lacks, such as manual backups
like `nginx/conf.d/edge-gateway.conf.before-*`, is **kept** and listed in the
play output as `untracked files on the server (kept): …`; delete those by hand
if they are no longer wanted. A shallow or incomplete local history only makes
the prune keep more.

Pruning never leaves those directories: the Compose file, the rendered `.env*`
files, backups and Docker volumes are outside them and are never listed. The
prune refuses to run when the checkout listing misses one of the directories
(a wipe instead of a mirror). The decision is
`roles/app/filter_plugins/asset_mirror.py`; built-in modules do the rest, with
no rsync on the server. `scripts/verify-asset-mirror.py` (CI job
`verifyAnsible`) runs the real tasks against a fixture git repository: a
tracked and deleted file is removed, an unknown manual file and the secrets
are kept.

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
- all seven public Blackbox probes (five `awesome.byst.re`, two
  `aitesters.byst.re` routes) currently succeed
- the emergency swap file and swappiness when `swap_enabled` is true
- every GraalVM native service runs with its expected `-Xmx` argument:
  `backend` `-Xmx384m`, `aitesters-backend` `-Xmx256m`, and `-Xmx64m` for
  `consumer`, `warehouse-service`, `aitesters-warehouse-service`,
  `payment-service`, `aitesters-payment-service`, `notification-service` and
  `aitesters-notification-service`
- the `warehouse`, `payment` and `notification` database roles of both
  databases own their schema, cannot read `public.orders` or `public.app_user`,
  cannot create in `public` and cannot use each other's schemas
- the direct warehouse-, payment- and notification-service health and OpenAPI
  routes, `/warehouse/v3/api-docs`, `/payment/v3/api-docs` and
  `/notification/v3/api-docs` through the gateway (both hosts), and `/api/v1/tracking/<unknown>` answering `404` from
  warehouse-service
- `awesome-watchdog.timer` is active and `awesome-watchdog run --dry-run`
  exits 0; the dry run and `awesome-watchdog diagnose` (readable OOM sources)
  are printed
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
- `watchdog`: host watchdog (containers, OOM, disk, memory, backups) with
  Telegram delivery and an optional dead-man ping
- `postgres_backup`: encrypted backups, restore checks, and the pre-deploy
  backup; both units notify Telegram through the watchdog on failure
- `deployment_silence`: bounded suppression of planned warning-level public
  endpoint and backend/consumer scrape alerts plus the bounded watchdog pause;
  critical alerts are never silenced
- `backend_upgrade`: opt-in quiesce (stop both backends and their services,
  quiesced backup) and the rescue restart of the stopped containers
- `app`: `prepare.yml` (gates, asset mirror, env rendering, Compose
  validation, pulls, docs build: no service touched) and `converge.yml`
  (Compose convergence); `main.yml` runs both for `reset-demo-state.yml`
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
- `alertmanager_telegram_bot_token` (also used by the host watchdog)
- `alertmanager_telegram_chat_id` (also used by the host watchdog)
- `watchdog_healthcheck_url` (optional dead-man ping URL; empty disables it)
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
- `notification_service_token`, `aitesters_notification_service_token`
- `notification_postgres_password`, `aitesters_notification_postgres_password`
- `notification_webhook_secret_encryption_password`,
  `notification_webhook_secret_encryption_salt`,
  `aitesters_notification_webhook_secret_encryption_password`,
  `aitesters_notification_webhook_secret_encryption_salt`

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
backend's JWKS and holds no signing key. The backends never call
payment-service (backend 3.16.0 removed `PAYMENT_BASE_URL`); each
payment-service polls its own backend's event feed for card refunds through
`BACKEND_BASE_URL`, set in Compose.

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
`https://awesome.byst.re/payment/v3/api-docs` and the `-Xmx64m` heap of both
payment-services.

## notification-service secrets and image gate

notification-service 1.0.0 (backend 3.21.0) needs eight Vault values (see
`vault.yml.example`):

| Key | Rule | Reaches |
| --- | --- | --- |
| `notification_service_token` | at least 32 characters (`openssl rand -hex 32`) | `.env.runtime` (backend) and `.env.notification` |
| `aitesters_notification_service_token` | at least 32 characters | `.env.aitesters` and `.env.aitesters-notification` |
| `notification_postgres_password` | at least 16 characters | `.env.notification`, `.env.postgres-roles` |
| `aitesters_notification_postgres_password` | at least 16 characters | `.env.aitesters-notification`, `.env.aitesters-postgres-roles` |
| `notification_webhook_secret_encryption_password` | at least 32 characters | `.env.notification` (`WEBHOOKS_SECRET_ENCRYPTION_PASSWORD`) |
| `notification_webhook_secret_encryption_salt` | at least 16 bytes in hex (`openssl rand -hex 16`) | `.env.notification` (`WEBHOOKS_SECRET_ENCRYPTION_SALT`) |
| `aitesters_notification_webhook_secret_encryption_password` | at least 32 characters, different from the stable one | `.env.aitesters-notification` |
| `aitesters_notification_webhook_secret_encryption_salt` | at least 16 bytes in hex | `.env.aitesters-notification` |

The `app` role refuses to deploy unless the two notification tokens differ from
each other and from every payment and warehouse token or webhook secret, and
the eight database passwords (superusers, warehouse, payment and notification
roles of both databases) are all distinct. The encryption key protects the
webhook signing secrets notification-service stores; changing it later makes
the stored secrets unreadable, so set it once.

`.env.notification` (root-owned, mode 0600) contains only
`NOTIFICATION_SERVICE_TOKEN`, `SPRING_DATASOURCE_PASSWORD`, the broker
credentials (`SPRING_ARTEMIS_USER`/`_PASSWORD` from `artemis_username` and
`artemis_password`: the stable site sends commerce emails to the `email` queue)
and the encryption key. `.env.aitesters-notification` holds the sandbox token,
role password and encryption key plus `LOCAL_EMAIL_OUTBOX_ACCESS_KEY`
(`local_email_outbox_access_key`): the sandbox keeps commerce emails in the
local outbox, like aitesters-backend. Both backends get their site's
`NOTIFICATION_SERVICE_TOKEN`; Compose sets `NOTIFICATIONS_DELIVERY=feed` and
`WEBHOOKS_ENABLED=false` on both.

The `postgres-roles` one-shots prepare the `notification` role and schema next
to `warehouse` and `payment`. The nightly aitesters reset and
`make ansible-reset-aitesters-state` also recreate
`aitesters-notification-service`, and the coordinated backend upgrade stops
both notification-services with the backends. Verification checks the role
isolation of `notification` (and that `warehouse` and `payment` cannot use its
schema), the direct routes `http://notification-service:4005` and
`http://aitesters-notification-service:4005`, `/notification/v3/api-docs`
through both gateway hosts, the `spring_notification_micrometer` scrape job,
the public probe of `https://awesome.byst.re/notification/v3/api-docs` (seven
public probes in total) and the `-Xmx64m` heap of both notification-services.
`CriticalContainerMissing` covers `notification-service`.

Deployment fails unless `notification-service` and
`aitesters-notification-service` use a published `tag@sha256`. Until
notification-service 1.0.0 is published the server Compose file carries
`slawekradzyminski/notification-service:1.0.0@sha256:PENDING_NOTIFICATION_SERVICE_DIGEST`,
so the gate fails on purpose; set `notification_service_allow_unpinned_image=true`
only for a deliberately pre-loaded image.

## Memory budget

The VPS has about 4.25 GiB of RAM and no swap. Container limits are safety
ceilings and are deliberately overcommitted: the long-running services' limits
added up to about 5.8 GiB, while the last measured host had 2.8 GiB available
(9 November 2026, after the native-image migration). Lean monitoring phase A
removes Grafana (640 MiB limit, about 450 MiB working set), bringing the limits
to about 5.2 GiB; the host watchdog is a one-minute systemd timer with no
resident memory.

This release adds two more 160 MiB containers, `payment-service` and
`aitesters-payment-service` (GraalVM native images with `-Xmx64m`, like the
warehouse-services, which measure 58 to 66 MiB each). Their limits add
320 MiB to the overcommitted total; the expected working set is about
120 to 140 MiB, which leaves roughly 2.6 GiB available. Measure
`MemAvailable` and the payment-services' working sets after the first deploy
and record them in `docs/CONTAINER_RELEASES.md`; if available memory drops
below 1.5 GiB, lower a limit (the `ContainerMemoryNearLimit` warnings show
which) before adding further services.

The distributed-lab release adds two more 160 MiB containers,
`notification-service` and `aitesters-notification-service` (GraalVM native,
`-Xmx64m`; 57 MiB measured on the lightweight profile, 14 November 2026). The
long-running limits now add up to **5,664 MiB (about 5.5 GiB)**: +320 MiB over
the 5,344 MiB before it. The expected extra working set is about 120 MiB, which
leaves roughly 2.4 GiB available. Measure `MemAvailable` and both
notification-services' working sets after the first deploy and record them in
`docs/CONTAINER_RELEASES.md`.

## Documentation wiki image

The `docs` service (the MkDocs wiki at `/docs/`, `mem_limit: 32m`) is the only
image built on the server. The `app` role mirrors `docs/` and `docs-site/` and
runs `docker compose build docs` in `prepare.yml`, before any service is
stopped (`docker compose up` then runs with `build: never`); the image is
static files on the digest-pinned `nginx:1.31.3-trixie` base (shared with the
gateway), so no registry release or digest pin is needed for documentation
edits (`awesome-localstack/docs:local`, `pull_policy: build`, exempt from
`verify-image-pins.py` like other `:local` builds). The build needs outbound
access to PyPI and jsDelivr. `verify` checks `http://docs/docs/` from the
gateway container and `/docs/` on both hosts.
