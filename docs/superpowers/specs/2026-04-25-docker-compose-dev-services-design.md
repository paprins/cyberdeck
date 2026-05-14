# Design: docker-compose for local dev companion services

**Date:** 2026-04-25  
**Status:** Approved

## Goal

Give developers a single `docker compose up` command to run the two companion content services (kiwix-serve and mbtileserver) locally, so they can test offline content without a Raspberry Pi. The FastAPI cyberdeck app continues to run on the host via `uv run uvicorn`.

## Scope

- **In:** `docker-compose.yml` at the repo root with `kiwix` and `mbtileserver` services
- **Out:** Dockerizing the cyberdeck FastAPI app; `.env` files; health checks; Dockerfiles

## Services

### kiwix

| Field   | Value                              |
|---------|------------------------------------|
| Image   | `ghcr.io/kiwix/kiwix-serve:latest` |
| Command | `kiwix-serve --port 8080 /data/zim/` |
| Volume  | `./data/zim:/data/zim:ro`          |
| Port    | `8080:8080`                        |
| Restart | `on-failure`                       |

Uses directory mode — kiwix-serve discovers ZIM files in `./data/zim/` automatically, no `library.xml` needed. Read-only mount since kiwix never writes to the ZIM directory.

### mbtileserver

| Field   | Value                                    |
|---------|------------------------------------------|
| Image   | `ghcr.io/consbio/mbtileserver:latest`    |
| Command | `mbtileserver --port 8081 --dir /data/maps` |
| Volume  | `./data/maps:/data/maps:ro`              |
| Port    | `8081:8081`                              |
| Restart | `on-failure`                             |

Serves `.mbtiles` files from `./data/maps/`. Read-only mount.

## Port mapping

Ports match the production systemd configuration and the `Settings` defaults in `app/config.py`:

| Service       | Port |
|---------------|------|
| kiwix-serve   | 8080 |
| mbtileserver  | 8081 |
| cyberdeck (host) | 8000 |

The FastAPI app reaches kiwix and mbtileserver at `localhost:8080` and `localhost:8081`, identical to production.

## Developer workflow

```bash
# Start companion services
docker compose up

# In a separate terminal, run the FastAPI app as usual
CYBERDECK_DATA_DIR=data uv run uvicorn app.main:app --reload --port 8000

# Stop companion services
docker compose down
```

## File created

- `docker-compose.yml` — repo root
