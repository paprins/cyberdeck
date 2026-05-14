# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Skills

**Always invoke skills before acting.** Check for relevant skills before writing code, designing UI, or planning features. Key rules:

- **Any feature or bugfix** → invoke `/feature-dev:feature-dev` for ANY feature work — see workflow below
- **Any UI/UX work** → invoke `impeccable` before writing frontend code; this is mandatory, not optional

## Design Context

Before any UI, design, copy, or marketing/visual change, **read `.impeccable.md` at the repo root first**. It is the canonical design context: users, brand personality, aesthetic direction, 4 anti-references, and the 7 tiebreaker principles (evidence over decoration; brand orange as signal not noise; calm under pressure; token-first; developer-reader first; WCAG 2.1 AA floor; four anti-references guardrail). Never hardcode hex values — use the CSS variables defined in `app/static/css/input.css` (`@theme` block). Visual reference for the UI: `mockup/code.html` (annotated HTML) and `mockup/screen.png` (screenshot).

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

# Compile Tailwind CSS (run after editing input.css or any template)
tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify
# NOTE: use the Homebrew `tailwindcss` binary — never pytailwindcss or a local ./tailwindcss binary
```

All environment variables use the `CYBERDECK_` prefix (e.g. `CYBERDECK_DATA_DIR=/data`).

## Frontend Stack

- **Templating**: Jinja2. All pages extend `app/templates/base.html` via `{% extends "base.html" %}` and fill `{% block content %}`.
- **Reactivity**: Alpine.js (`app/static/js/alpine.min.js`). Use `x-data`, `x-show`, `x-text`, `@click`, etc. No build step for JS.
- **Styling**: Tailwind CSS v4. Tokens live in the `@theme` block in `app/static/css/input.css`; compiled output is `app/static/css/app.css`. Run the Tailwind compile command above whenever templates or input.css change.
- **Icons**: Material Symbols Outlined (`<span class="material-symbols-outlined">`), served from `app/static/` (self-hosted, offline-safe).
- **Static assets layout**: `app/static/css/`, `app/static/js/`, `app/static/fonts/` (Space Grotesk + Inter woff2 files).

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

## Feature Development Workflow (MANDATORY)

**CRITICAL: You MUST invoke `/feature-dev:feature-dev` for any feature work. DO NOT just say you will use it and then implement directly. You must actually call the Skill tool.**

### When to Use

- New features (endpoints, pages, widgets, services)
- EPIC or USER STORY implementation
- Multi-file changes
- UI additions or modifications
- API endpoint creation
- Database model changes
- Significant refactoring

### How to Invoke

```
Skill(skill="feature-dev:feature-dev", args="<description of the feature>")
```

### The 7-Phase Process (DO NOT SKIP PHASES)

1. **Discovery** — Understand requirements, create TODO list
2. **Codebase Exploration** — Launch 2-3 code-explorer agents in parallel
3. **Clarifying Questions** — Ask user about edge cases, preferences, ambiguities (WAIT FOR ANSWERS)
4. **Architecture Design** — Launch 2-3 code-architect agents, present options, get user approval
5. **Implementation** — ONLY after user approves architecture
6. **Quality Review** — Launch 3 code-reviewer agents (bugs, conventions, simplicity)
7. **Summary** — Document what was built and update user-story in epic (status + date)

### FORBIDDEN Behaviors

- DO NOT say "I'll use feature-dev" and then implement directly
- DO NOT skip the clarifying questions phase
- DO NOT start implementation without explicit user approval
- DO NOT skip the quality review phase