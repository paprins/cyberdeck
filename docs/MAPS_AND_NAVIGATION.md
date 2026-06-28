# Maps & Navigation

How to add an offline map for a region and enable turn-by-turn navigation on it.

## The two data layers

A navigable region needs **two independent datasets**. They come from the same
OpenStreetMap data but are built and served differently:

| Layer | What it is | File | Served by | Module kind |
| ----- | ---------- | ---- | --------- | ----------- |
| **Display** | Vector tiles you see on screen | `data/maps/{id}.mbtiles` | `mbtileserver` (`:8081`, proxied at `/maps`) | `mbtiles` |
| **Routing** | A routable graph for the engine | `data/routing/{id}.tar` | `valhalla` (`:8082`, proxied via `/map/{id}/route`) | `routing` |

The display layer alone gives you a pan/zoom map with coordinate readout and
measurement. **Navigation additionally requires the routing layer.** A region
that has only `mbtiles` is display-only; the NAVIGATE panel is hidden until a
matching, active `routing` module exists.

> **Engine:** Routing uses [Valhalla](https://github.com/valhalla/valhalla) —
> one tile set serves walk/bike/car and produces turn-by-turn instructions
> natively.

## Quick start (helper script)

`scripts/enable-navigation.sh` automates Part 2 (prepare routing tiles → register
→ stage → start the engine). The display `.mbtiles` must already be in place.

```bash
# On a Pi: install a tar you built on a workstation (recommended).
scripts/enable-navigation.sh --map-id netherlands-260525 \
    --routing-tar ~/netherlands-routing.tar

# On a workstation: download an extract and build the tar locally.
scripts/enable-navigation.sh --map-id netherlands-260525 \
    --pbf-url https://download.geofabrik.de/europe/netherlands-latest.osm.pbf
```

The routing module id defaults to `<map-id>-routing`; override with `--routing-id`.
The script refuses to build on an ARM/Pi host unless you pass `--force-build`.
The manual steps below explain what it does and how to do it by hand.

## Prerequisites

- **Docker** (used to build the routing tiles, and to run the engines in dev).
- **Disk:** the OSM extract (≈1.4 GB for the Netherlands) is needed only during
  the build; the resulting routing tar is smaller (≈870 MB for NL). The display
  `.mbtiles` is separate (≈0.8 GB for NL).
- **RAM for the build:** give Docker **≥4–8 GB**. The Pi should **not** build
  tiles — build on a workstation and copy the resulting `.tar` over.
- The companion services from `docker-compose.yml` (`mbtileserver`, `valhalla`).

---

## Part 1 — Display map (`.mbtiles`)

The display layer is an OpenMapTiles-schema vector `.mbtiles`. Obtain one (e.g.
generated with [planetiler](https://github.com/onthegomap/planetiler) from a
Geofabrik extract, or downloaded from a provider) and place it:

```
data/maps/{id}.mbtiles      # e.g. data/maps/netherlands-260525.mbtiles
```

Register it as an `mbtiles` module so it appears in the **NAVIGATION** category.
The `{id}` in the filename must match the module `id`:

```bash
cd <repo-root>
uv run python - <<'PY'
from pathlib import Path
from app.config import Settings
from app.models.registry import Module
from app.services.registry import load_registry, save_registry

s = Settings(data_dir=Path("data"))
reg = load_registry(s)
MAP_ID = "netherlands-260525"     # must equal the .mbtiles filename stem

reg.modules = [m for m in reg.modules if m.id != MAP_ID]
reg.modules.append(Module(
    id=MAP_ID,
    display_name="Netherlands",
    category="navigation",
    description="Vector tiles of the Netherlands (OpenStreetMap).",
    latest_version="2026-05-25",
    size_gb=0.8,
    kind="mbtiles",
    checksum="sha256:local",       # any value for a hand-placed file
    installed_version="2026-05-25",
    active=True,
))
save_registry(s, reg)
print("registered map:", MAP_ID)
PY
```

The region is now viewable at `/map/{id}` (e.g. `/map/netherlands-260525`).

---

## Part 2 — Routing tiles (enables navigation)

### 2.1 Download the OSM extract and verify it

Use a [Geofabrik](https://download.geofabrik.de/) regional `.osm.pbf`. **Verify
the checksum** — a truncated download is the most common cause of a failed build
(it surfaces as `PBF error: unexpected EOF`).

```bash
cd <repo-root>/data/routing

curl -fL --retry 3 -o netherlands-latest.osm.pbf \
  https://download.geofabrik.de/europe/netherlands-latest.osm.pbf

# Compare against the published checksum:
curl -s https://download.geofabrik.de/europe/netherlands-latest.osm.pbf.md5
md5 -q netherlands-latest.osm.pbf        # macOS;  use `md5sum` on Linux
```

The two hashes must match before continuing.

### 2.2 Build the Valhalla tile set

Run the build image **once**. The flags force a build from the PBF (the image
otherwise defaults to "serve existing tiles" and skips building):

```bash
cd <repo-root>
docker run --rm -v "$PWD/data/routing:/custom_files" \
  -e use_tiles_ignore_pbf=False \
  -e force_rebuild=True \
  -e build_tar=True \
  -e serve_tiles=False \
  ghcr.io/nilsnolde/docker-valhalla/valhalla:latest
```

This writes `data/routing/valhalla_tiles.tar`. The build takes ~15–30 min for a
country-sized extract.

### 2.3 Name the tar and clean up

The app stages the **active region's** `{id}.tar`, so rename the output to match
the routing module id you'll register. Then remove build by-products:

```bash
cd <repo-root>/data/routing
mv valhalla_tiles.tar netherlands-routing.tar
rm -rf valhalla_tiles valhalla.json file_hashes.txt duplicateways.txt \
       netherlands-latest.osm.pbf      # the .pbf is only needed for the build
```

Final state: `data/routing/netherlands-routing.tar` and nothing else.

### 2.4 Register the routing module

`routing_for` links the routing tiles to the display region's id:

```bash
cd <repo-root>
uv run python - <<'PY'
from pathlib import Path
from app.config import Settings
from app.models.registry import Module
from app.services.registry import load_registry, save_registry

s = Settings(data_dir=Path("data"))
reg = load_registry(s)
ROUTING_ID = "netherlands-routing"     # must equal the .tar filename stem
MAP_ID     = "netherlands-260525"      # the mbtiles region it serves

reg.modules = [m for m in reg.modules if m.id != ROUTING_ID]
reg.modules.append(Module(
    id=ROUTING_ID,
    display_name="Netherlands Routing",
    category="navigation",
    description="Valhalla routing tiles for the Netherlands.",
    latest_version="1",
    size_gb=2.0,
    kind="routing",
    checksum="sha256:local",
    routing_for=MAP_ID,
    installed_version="1",
    active=True,
))
save_registry(s, reg)
print("registered routing:", ROUTING_ID, "-> serves:", MAP_ID)
PY
```

> Routing modules are **backing data** — they never appear as their own card in
> the content grid, and they aren't counted in the category total. They simply
> light up the NAVIGATE panel on the linked map.

### 2.5 Start the engine

On startup the app reconciles the active routing module: it stages a same-dir
symlink `data/routing/valhalla_tiles.tar → netherlands-routing.tar` and (re)starts
Valhalla. So start the app, then bring the engine up:

```bash
# dev
CYBERDECK_DATA_DIR=data uv run uvicorn app.main:app --port 8000 &
docker compose up -d mbtileserver valhalla
```

---

## Verify

```bash
# 1. Engine loaded the tile set?
curl -s http://127.0.0.1:8082/status

# 2. End-to-end route through the app (Amsterdam → Utrecht, by car):
curl -s "http://127.0.0.1:8000/map/netherlands-260525/route?from=52.3789,4.9005&to=52.0894,5.1101&mode=car" | head -c 300
```

A successful route returns `{summary, geometry, maneuvers}`. Then open
`/map/netherlands-260525`, click the **directions** icon (top-right), set A and B
by tapping the map or typing `lat, lon`, choose WALK/BIKE/CAR, and press
**NAVIGATE**.

---

## How it fits together

```
data/maps/{id}.mbtiles ──► mbtileserver :8081 ──► /maps ──► MapLibre (display)

data/routing/{id}.tar ◄── valhalla_tiles.tar (symlink, staged by the app)
        │
        └─► valhalla :8082 ◄── GET /map/{id}/route ◄── NAVIGATE panel
```

- The viewer shows NAVIGATE only when a `routing` module with
  `routing_for == {map id}` is **installed and active**.
- `GET /map/{id}/route?from=&to=&mode=` builds the Valhalla request, decodes the
  route geometry, and returns clean JSON (`mode`: `walk`→pedestrian,
  `bike`→bicycle, `car`→auto).

### One active region at a time

Valhalla loads exactly **one** tile extract and does **not** hot-reload. The app
stages whichever routing module is active and restarts Valhalla on change. If you
install routing for several regions, only the active one is routable; activating
another (via the module's activate flow) restages its tar and restarts the engine
(the first route afterwards is slightly slower as the tiles page in).

---

## Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| Build aborts with `PBF error: unexpected EOF` | Truncated download. Re-download and verify the md5 (§2.1). |
| Build logs `use_tiles_ignore_pbf True … Couldn't find usable tiles` | Build was skipped. Pass `use_tiles_ignore_pbf=False -e force_rebuild=True` (§2.2). |
| `valhalla` container restart-loops | No `valhalla_tiles.tar` present. Start the app first so it stages the symlink, or check the `{id}.tar` exists. |
| Route returns `409` | No installed+active routing module for this region (check `routing_for`). |
| Route returns `502` | Engine unreachable — `docker compose logs valhalla`. |
| Route returns `422` | No path between the points, or beyond the mode's distance limit (pedestrian defaults to 250 km). |
| `valhalla_tiles.tar` keeps disappearing | The app's reconcile deletes a stray symlink when no matching `{id}.tar` exists. Make sure the tar is named after the registered module. |

## Production note (Pi)

`docker-compose.yml` is the dev convenience. On the Pi the companion services run
under `systemd` (see [DEPLOY.md](DEPLOY.md)); Valhalla needs an equivalent unit
that serves `/data/routing/valhalla_tiles.tar` on `:8082` with
`use_tiles_ignore_pbf=True` / `build_tar=False`. Always copy a **prebuilt** tar
to the Pi — never build tiles on the device.
