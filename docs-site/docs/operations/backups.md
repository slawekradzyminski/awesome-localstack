# Backups

Production installs two systemd timers:

| Timer | What it does |
| --- | --- |
| `awesome-postgres-backup.timer` | Daily encrypted SQL archive of PostgreSQL |
| `awesome-postgres-restore-check.timer` | Weekly restore of the newest archive into an isolated, disposable PostgreSQL container |

Every deploy also takes an encrypted backup before replacing containers, and
`make ansible-deploy-backend-upgrade` takes a **quiesced** one with both
backends stopped.

- Encryption: AES-256-CBC, PBKDF2, 200,000 iterations, passphrase
  `backup_encryption_passphrase` from Vault (keep an offline copy). No
  plaintext dump touches the disk; each archive has a SHA-256 sidecar.
- Retention: 7 daily archives in
  `/var/backups/awesome-localstack/postgres/daily`, 4 Sunday archives in
  `.../weekly`.
- Off-host copy: optional `backup_remote_target` (rsync over SSH).

```bash
sudo systemctl start awesome-postgres-backup.service
sudo systemctl start awesome-postgres-restore-check.service
systemctl list-timers 'awesome-postgres-*'
```

!!! note "Schema ownership after a restore"
    Archives are taken with `--no-owner`, so restored `warehouse` and
    `payment` schemas belong to the superuser at first. Recreating
    warehouse-service and payment-service runs the `postgres-roles` one-shot,
    which hands the schemas and their tables back to their roles.

The backup timers cover the stable `postgres` service; the sandbox database
is rebuilt from scratch every night.

Full procedure: [Production backups](../reference/PRODUCTION_BACKUPS.md).
