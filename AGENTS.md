# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Skills

**Always invoke skills before acting.** Check for relevant skills before writing code, designing UI, or planning features. Key rules:

- **Any feature or bugfix** → invoke `superpowers:brainstorming` before planning, `superpowers:test-driven-development` before writing code
- **Any UI/UX work** → invoke `impeccable` before writing frontend code; this is mandatory, not optional
- **Multi-step implementation** → use `superpowers:writing-plans` then `superpowers:executing-plans`
- **Before claiming done** → invoke `superpowers:verification-before-completion`

## Design Context

Before any UI, design, copy, or marketing/visual change, **read `.impeccable.md` at the repo root first**. It is the canonical design context: users, brand personality, aesthetic direction, 4 anti-references, and the 7 tiebreaker principles (evidence over decoration; brand orange as signal not noise; calm under pressure; token-first; developer-reader first; WCAG 2.1 AA floor; four anti-references guardrail). Never hardcode hex values — use the CSS tokens in `app/globals.css` and the Tailwind theme extension.

## Commands

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

All environment variables use the `CYBERDECK_` prefix (e.g. `CYBERDECK_DATA_DIR=/data`).

## Architecture

This is a **Raspberry Pi offline-first device** (cyberdeck). The FastAPI backend manages downloadable content modules (ZIM files for Kiwix, mbtiles for maps). A Chromium kiosk displays the web UI at boot.

**Data flow:**
- `Settings` (`app/config.py`) — single source of truth for paths and ports; injected everywhere
- `Registry` + `Module` (`app/models/registry.py`) — Pydantic models; `registry.json` is the on-disk state
- `app/services/registry.py` — all registry mutations go through here; always load→modify→save, never write JSON directly
- `app/main.py` — FastAPI app factory (`create_app(settings)`); the module-level `app` is for production, tests pass `tmp_settings`

**Three companion services run alongside the FastAPI app:**
- `kiwix-serve` — serves ZIM files on port 8080
- `mbtileserver` — serves map tiles on port 8081
- `cyberdeck` (FastAPI) — control plane on port 8000

Activating a module in the registry must eventually be reflected in the config of those services — that integration is not yet built.

## Coding Principles

**Think before coding.** State assumptions explicitly. If multiple interpretations exist, present them — don't pick silently. If something is unclear, stop, ask and present your recommendation.

**Simplicity first.** Minimum code that solves the problem. No features beyond what was asked, no abstractions for single-use code, no error handling for impossible scenarios. Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

**Surgical changes.** Touch only what you must. Don't improve adjacent code or refactor things that aren't broken. Match existing style. Every changed line should trace directly to the user's request.

**Goal-driven execution.** Transform tasks into verifiable goals — "fix the bug" → "write a test that reproduces it, then make it pass". For multi-step tasks, state a brief plan with a verify checkpoint per step.

## Testing conventions

- `conftest.py` provides `tmp_settings` (Settings pointing at `tmp_path`) and `clean_cyberdeck_env` (autouse, strips `CYBERDECK_*` env vars)
- Use `tmp_settings` for any test that touches the filesystem
- HTTP tests use `httpx.AsyncClient` with `ASGITransport` — no real server needed
- `asyncio_mode = "auto"` — async tests work without `@pytest.mark.asyncio`
