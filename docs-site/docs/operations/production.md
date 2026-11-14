# Production deployment

Production runs the `docker-compose.server.yml` stack on one VPS (1 vCPU,
about 4.25 GiB RAM, no swap) in `/opt/awesome-localstack`, serving
`awesome.byst.re` (stable) and `aitesters.byst.re` (nightly-reset sandbox).
Everything is done with Ansible from a laptop; nothing is edited by hand on
the server.

## Commands

| Command | Effect |
| --- | --- |
| `make deploy-preflight` | Local checks the deploy targets run first: server Compose config and the strict docs image build |
| `make ansible-deploy` | Converge the stack and run verification |
| `make ansible-deploy-backend-upgrade` | Prepare the release, then stop both backends, quiesced encrypted backup, deploy (for migrations or ciphertext changes) |
| `make ansible-verify` | Only the health checks |
| `make ansible-cleanup` | Checksum- and retention-guarded container and image cleanup |
| `make ansible-reset-demo-state` | **Destructive**: delete the PostgreSQL volume and Mailpit state, redeploy |
| `make ansible-reset-aitesters-state` | Recreate the sandbox database, backend, warehouse-, payment- and notification-service |
| `make ansible-ssh`, `make ansible-tunnel-prometheus`, `make ansible-tunnel-mailpit` | Shell and SSH tunnels (Prometheus `:9090`, Mailpit `:8025`) |
| `make ansible-edit-vault` | Edit the encrypted Vault |

## What `deploy.yml` does

```mermaid
flowchart TB
    P[Laptop preflight: compose config,<br/>strict docs build] --> A[Swap check]
    A --> W[Install host watchdog]
    W --> B[Encrypted backup]
    B --> R[app prepare: gates, asset mirror, env files,<br/>compose config, pulls, docs image]
    R --> C[Silence warnings and pause<br/>watchdog container checks 15 min]
    C --> Q{backend upgrade?}
    Q -- yes --> S[Stop both backends and their services,<br/>quiesced backup]
    Q -- no --> D
    S --> D[app converge: docker compose up,<br/>recreate gateway and edge]
    D --> E[verify role]
    E --> F[Expire silences, resume watchdog]
    F --> G[Cleanup]
    S -. failure before up .-> X[Restart the stopped containers,<br/>fail with runbook]
```

Everything that can fail for a reason unrelated to the database migration
runs **before** any service is stopped. The `app` role's `prepare.yml`
validates the Vault keys and the image gates; copies the Compose file;
mirrors the `nginx`, `prometheus`, `alertmanager`, `postgres`, `docs`,
`docs-site` and other asset directories (a file the repository tracked and
has since deleted is deleted on the server; files git never tracked there,
such as manual backups, and the rendered `alertmanager/secrets` are kept and
listed as `untracked files on the server (kept)`); renders
`.env.runtime`, `.env.warehouse`, `.env.payment`, `.env.notification` and the `.env.aitesters*`
files from Vault; runs `docker compose config --quiet`; pulls missing images;
and builds the docs image with `mkdocs build --strict`. Only then does the
optional quiesce stop the backends, and `converge.yml` runs
`docker compose up` and recreates `gateway` and `edge`.

A deploy that leaves the gateway returning `502` is a **failed** deploy:
verification is part of the playbook, not a follow-up.

## Secrets (Ansible Vault)

| Key | Used by |
| --- | --- |
| `postgres_password` | PostgreSQL superuser, backend datasource |
| `jwt_signing_key`, `aitesters_jwt_signing_key` | RS256 signing keys (distinct; base64 PKCS#8) |
| `warehouse_service_token`, `aitesters_warehouse_service_token` | warehouse → backend internal API |
| `warehouse_postgres_password`, `aitesters_warehouse_postgres_password` | `warehouse` database roles |
| `payment_service_token`, `aitesters_payment_service_token` | payment ↔ backend internal APIs |
| `payment_webhook_secret`, `aitesters_payment_webhook_secret` | payment result HMAC |
| `payment_postgres_password`, `aitesters_payment_postgres_password` | `payment` database roles |
| `notification_service_token`, `aitesters_notification_service_token` | notification → backend internal API (event feed, webhook export) |
| `notification_postgres_password`, `aitesters_notification_postgres_password` | `notification` database roles |
| `notification_webhook_secret_encryption_password` / `_salt` and their `aitesters_` variants | encryption of the webhook secrets notification-service stores |
| `aitesters_postgres_password` | sandbox PostgreSQL |
| `app_mfa_encryption_password`, `app_mfa_encryption_salt` | TOTP secret and webhook secret encryption |
| `app_bootstrap_admin_*` | the production admin account |
| `artemis_username`, `artemis_password` | broker account |
| `alertmanager_telegram_bot_token`, `alertmanager_telegram_chat_id` | Alertmanager and the host watchdog |
| `watchdog_healthcheck_url` | optional dead-man ping (empty disables it) |
| `backup_encryption_passphrase`, `backup_remote_target` | backups |
| `local_email_outbox_access_key` | sandbox outbox secondary key |
| `production_ssh_*` | connection |

The `app` role refuses to deploy when a required key is missing, too short or
reused where it must be distinct (for example the two signing keys). Each
service receives only its own secrets: warehouse-service gets
`.env.warehouse` (service token, database password), payment-service gets
`.env.payment` (service token, webhook secret, database password),
notification-service gets `.env.notification` (service token, database
password, broker credentials, webhook secret encryption key).

## Image gates

- Every remotely pulled image is pinned as `tag@sha256:<digest>`.
- The app role stops if `docker-compose.server.yml` does not pin a **published**
  warehouse-, payment- or notification-service image (the server cannot build GraalVM
  native images).
- The only locally built image on the server is the small `docs` wiki
  (`awesome-localstack/docs:local`), built from the deployed `docs-site/`
  directory; see [This documentation site](docs-site.md).

## Verification (`verify` role)

After every deploy and on `make ansible-verify`:

- every Compose service is running and one-shots exited `0`;
- every running container uses exactly the image its Compose reference
  resolves to;
- the `warehouse`, `payment` and `notification` roles cannot read backend tables or each other's schemas;
- PostgreSQL accepts the Vault password;
- a JMS contract email travels Artemis → consumer → Mailpit;
- direct routes (`http://warehouse-service:4003/...`, `http://payment-service:4004/...`,
  `http://notification-service:4005/...`,
  `http://docs/docs/`) answer from inside the gateway container;
- Prometheus targets are healthy, rules and Alertmanager are loaded, all seven
  public HTTPS probes succeed;
- `awesome-watchdog.timer` is active and a watchdog dry run exits `0`; its
  output and the readable OOM sources (`awesome-watchdog diagnose`) are printed;
- native-image heaps are bounded;
- gateway routes answer as expected on both hosts, for example `/login` 200,
  `/v3/api-docs` 200, `/warehouse/v3/api-docs` 200, `/payment/v3/api-docs` 200,
  `/notification/v3/api-docs` 200, `/docs/` 200, `/api/v1/tracking/VERIFY-UNKNOWN-TRACKING` 404,
  `/internal/v1/orders/1` 404, `/mailpit/` 404;
- the bootstrap admin can sign in and the catalog is present; the sandbox
  admin can sign in, traffic diagnostics and the outbox access key work;
- GraphQL and native gRPC surfaces respond.

## Recovering from a failed deploy

The play ends with a message naming the failed task and the state it left:

- **Preflight or before the quiesce**: nothing was stopped; the previous
  release still serves traffic. Fix and rerun the same make target.
- **After the quiesce, before `docker compose up`** (for example the quiesced
  backup): the rescue restarts the exact containers it stopped and waits until
  they are healthy. No migration ran. Fix and rerun.
- **From `docker compose up` on**: migrations may have run, so the old
  backends are not restarted. Fix and rerun (the play is idempotent), or roll
  back by re-pinning the previous release and restoring the quiesced backup
  ([Backups](backups.md)).

Silences and the watchdog pause expire after 15 minutes. Never delete deployed
files by hand on the server: the asset mirror prunes what the repository
tracked and removed.
Details: [Ansible — Recovering from a failed deploy](../reference/ANSIBLE.md#recovering-from-a-failed-deploy).

More: [Ansible](../reference/ANSIBLE.md), [SSH server](../reference/SSH_SERVER.md),
[SSH tunnelling](../reference/SSH_TUNNELLING.md),
[Production edge proxy](../reference/PRODUCTION_EDGE_PROXY.md).
