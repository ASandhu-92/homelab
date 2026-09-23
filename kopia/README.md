# Kopia: Encrypted, Deduplicated Backups

## What
Kopia run as a server: a scheduled snapshot engine plus a web UI/API over an
encrypted, content-addressed, deduplicated repository. One repository can back
up many source paths and hosts.

## Why
Backups only matter when they are (a) encrypted at rest, (b) space-efficient
enough that you keep long retention, and (c) stored somewhere the primary
failure can't reach. Kopia does all three: client-side encryption, block-level
dedup + compression, and pluggable backends (local, NFS, S3, Backblaze B2, GCS).

## Files
| File | Purpose |
|------|---------|
| `compose.yaml` | Kopia server pinned to `0.23.1`, behind-a-proxy config, healthcheck. |
| `.env.example` | Server credentials + repository encryption password (copy to `.env`). |

## Usage
```bash
cp .env.example .env      # set credentials + repository password
docker compose up -d
```

### Repository creation
Create the repository once (encryption is chosen at creation time):
```bash
# Local/NFS filesystem backend:
docker compose exec kopia kopia repository create filesystem --path=/repository
# Object storage (recommended for off-box copies):
docker compose exec kopia kopia repository create s3 \
  --bucket=my-backups --endpoint=s3.example.com \
  --access-key=... --secret-access-key=...
```
The repository password (`KOPIA_REPOSITORY_PASSWORD`) is set at creation and
cannot be recovered, only rotated by someone who already has it.

### Encryption model
All encryption and deduplication happen **client-side, before data leaves the
host**. The backend (even a third-party bucket) only ever sees opaque,
encrypted content-addressed blocks. Default cipher is AES-256-GCM with per-repo
key derivation; the human-held secret is the repository password.

### Policy examples (retention)
Retention is expressed as a policy, globally or per source path:
```bash
docker compose exec kopia kopia policy set --global \
  --keep-latest=10 --keep-hourly=24 --keep-daily=14 \
  --keep-weekly=8 --keep-monthly=12 --keep-annual=3
# Snapshot schedule (e.g. hourly):
docker compose exec kopia kopia policy set --global --snapshot-interval=1h
```

### Off-box replication rationale
A backup on the same box, same disk, or same building as the source shares its
failure modes: ransomware, a bad `rm`, a controller failure, fire, theft. The
3-2-1 rule (3 copies, 2 media, 1 off-site) exists because on-box redundancy is
not a backup. Point a second Kopia repository at object storage or a remote
host, or use `kopia repository sync-to` to replicate the local repo off-box on
a schedule.

### Restore-test discipline
**A backup you haven't restored is a hope, not a backup.** Backups fail
silently, a broken schedule, an unreadable repo, a forgotten password, and
you only discover it at the exact moment you can least afford to. Make restore
a *routine*, not an emergency:
- On a schedule (monthly is a sane floor), restore a real snapshot to a scratch
  location and diff it against the source or verify checksums.
- Practise a full recovery from *only* the off-box copy + the password, prove
  you can rebuild with nothing but what survives the primary site.
- Run `kopia snapshot verify` periodically to detect repository corruption
  before a restore needs it.
- Treat "we have backups" as unproven until the last successful restore is
  recent and documented.

Tested on Docker (published port removed): the server started, stayed
`starting` until a repository existed, then went healthy after `kopia
repository create filesystem --path=/repository`. The healthcheck checks the
repository, so expect "unhealthy" until you create or connect one.

## Integration
Terminate TLS at a reverse proxy and require an auth/SSO middleware in front of
the Kopia UI, `--insecure` in the compose file assumes exactly that and must
never face the internet directly. Point monitoring (see the `gatus` folder)
at snapshot freshness so a stalled backup job pages you.
