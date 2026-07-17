# Production PostgreSQL backups

Production deployments install two systemd timers:

- `awesome-postgres-backup.timer` creates a daily encrypted SQL archive.
- `awesome-postgres-restore-check.timer` restores the newest archive into an
  isolated disposable PostgreSQL container every week.

The deployment also creates a backup immediately before replacing application
containers when the production PostgreSQL service is running.

## Required vault configuration

Add a dedicated encryption passphrase to the encrypted production vault:

```yaml
backup_encryption_passphrase: a-separate-random-secret-of-at-least-32-characters
```

Keep an offline copy of this passphrase. The encrypted backups cannot be
recovered without it.

For off-host copies, configure an existing rsync destination:

```yaml
backup_remote_target: backup@example.net:/srv/backups/awesome-testing
```

The server's root account must already have SSH authentication and host-key
verification configured for the destination. When the setting is empty, local
encrypted backups and restore verification still run, but the setup does not
protect against loss of the entire server.

## Retention and locations

By default, the server keeps:

- 7 newest daily archives under
  `/var/backups/awesome-localstack/postgres/daily`.
- 4 newest Sunday archives under
  `/var/backups/awesome-localstack/postgres/weekly`.

Every encrypted archive has a SHA-256 checksum sidecar. No plaintext dump is
written to disk.

## Manual operations

Create a backup:

```bash
sudo systemctl start awesome-postgres-backup.service
sudo journalctl -u awesome-postgres-backup.service
```

Verify the newest backup by performing an isolated restore:

```bash
sudo systemctl start awesome-postgres-restore-check.service
sudo journalctl -u awesome-postgres-restore-check.service
```

Inspect timer state:

```bash
systemctl list-timers 'awesome-postgres-*'
```

## Recovery

Copy an encrypted archive and its `.sha256` sidecar to a trusted machine with
Docker, GNU gzip, and OpenSSL. Verify the checksum, decrypt it, and pipe the SQL
into a clean PostgreSQL 16.14 database. Use the same OpenSSL parameters as the
automation: AES-256-CBC, PBKDF2, and 200,000 iterations.
