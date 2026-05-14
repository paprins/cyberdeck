# Docker Compose Dev Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `docker-compose.yml` at the repo root so developers can start kiwix-serve and mbtileserver locally with a single command.

**Architecture:** Two services (kiwix, mbtileserver) bind-mount `./data/zim` and `./data/maps` read-only and expose the same ports (8080, 8081) that the production systemd services use, so the FastAPI app running on the host reaches them at identical addresses.

**Tech Stack:** Docker Compose v2, `ghcr.io/kiwix/kiwix-serve:latest`, `ghcr.io/consbio/mbtileserver:latest`

---

## File map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docker-compose.yml` | Defines kiwix and mbtileserver services |
| Modify | `AGENTS.md` | Document `docker compose up` in Commands section |

---

### Task 1: Create docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Write the file**

Create `docker-compose.yml` at the repo root with this exact content:

```yaml
services:
  kiwix:
    image: ghcr.io/kiwix/kiwix-serve:latest
    command: --port 8080 /data/zim/
    volumes:
      - ./data/zim:/data/zim:ro
    ports:
      - "8080:8080"
    restart: on-failure

  mbtileserver:
    image: ghcr.io/consbio/mbtileserver:latest
    command: --port 8081 --dir /data/maps
    volumes:
      - ./data/maps:/data/maps:ro
    ports:
      - "8081:8081"
    restart: on-failure
```

- [ ] **Step 2: Validate YAML syntax**

Run:
```bash
docker compose config
```

Expected: Docker prints the resolved compose config with no errors. If Docker isn't installed in the current environment, skip to Task 2 — the smoke test is a manual step.

---

### Task 2: Update AGENTS.md

**Files:**
- Modify: `AGENTS.md` (Commands section, after the dev server line)

- [ ] **Step 1: Add docker compose command to the Commands section**

In `AGENTS.md`, find the Commands block ending with:

```
# Run the dev server
CYBERDECK_DATA_DIR=data uv run uvicorn app.main:app --reload --port 8000
```

Add immediately after that line, still inside the same code block:

```
# Start companion content services (kiwix on :8080, mbtileserver on :8081)
docker compose up
```

The full Commands block should now look like:

```bash
# Install deps
uv sync --extra dev

# Run all tests
uv run pytest

# Run a single test file or test by name
uv run pytest tests/test_registry.py
uv run pytest -k "test_merge_remote_manifest"

# Run the dev server
CYBERDECK_DATA_DIR=data uv run uvicorn app.main:app --reload --port 8000

# Start companion content services (kiwix on :8080, mbtileserver on :8081)
docker compose up
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml AGENTS.md
git commit -m "feat: add docker-compose for local kiwix and mbtileserver dev services"
```

---

## Manual smoke test (after commit)

Run from the repo root:

```bash
docker compose up
```

Expected:
- Docker pulls both images on first run
- `kiwix` service starts and logs something like `Starting Kiwix Server...`
- `mbtileserver` service starts and logs `Listening on :8081`
- Visiting `http://localhost:8080` in a browser shows the Kiwix interface (with ZIM files listed if `./data/zim/` contains `.zim` files)
- Visiting `http://localhost:8081/services` returns a JSON list of available map tile sets (empty array `[]` if `./data/maps/` is empty)

Stop with `Ctrl-C` or `docker compose down`.
