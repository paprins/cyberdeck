# Migrations

Per-release Python scripts that update on-disk state (`/data/...`) during an upgrade.

Each release that needs a migration adds one file: `migrations/v<version>.py`. It runs
inside the **new** venv before the symlink swap. Selection is `installed < script <= new`
(semver). If a migration exits non-zero, the upgrade aborts and the new version dir is
removed — the system stays on the old version.

## Contract

Each migration is a standalone script invokable as `python migrations/vX.Y.Z.py`.
Use environment variables to find data:

- `CYBERDECK_DATA_DIR` — set by systemd; usually `/data`.

Make migrations **idempotent**. If a retry happens after a fix, the migration must
tolerate already-applied state (check-before-mutate).
