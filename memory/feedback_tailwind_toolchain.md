---
name: Tailwind CSS toolchain
description: How to recompile Tailwind CSS in this project — which binary to use and what command to run
type: feedback
---

Use `tailwindcss` (Homebrew, `/opt/homebrew/bin/tailwindcss`) to recompile, not pytailwindcss or any local binary.

Command: `tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify`

**Why:** The project uses Tailwind v4 with a Homebrew-installed CLI. Other binaries (pytailwindcss, npx, local) are not installed or produce different output.

**How to apply:** Any time you change `app/static/css/input.css` (theme tokens, utilities), run the above command to regenerate `app/static/css/app.css`.
