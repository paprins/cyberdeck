# Cyberdeck — task runner. Run `just` to list recipes.

# Data directory used by the app (override: `just data_dir=/data run`)
data_dir := "data"
port := "8000"

# List available recipes
default:
    @just --list

# Start the dev server with auto-reload
run:
    CYBERDECK_DATA_DIR={{data_dir}} uv run uvicorn app.main:app --reload --port {{port}}

# Install dependencies (including dev extras)
install:
    uv sync --extra dev

# Run the test suite
test *args:
    uv run pytest {{args}}

# Compile Tailwind CSS (run after editing input.css or templates)
css:
    tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify

# Start companion content services (kiwix :8080, mbtileserver :8081)
services:
    docker compose up -d
