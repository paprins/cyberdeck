"""Offline turn-by-turn routing for map regions backed by a Valhalla extract.

    GET /map/{id}/route?from=<lat,lon>&to=<lat,lon>&mode=walk|bike|car

Resolves the region's installed + active routing module, calls the local Valhalla
service, and returns a clean payload (a GeoJSON LineString plus maneuvers) so the
frontend stays thin. Valhalla loads a single tile extract at a time, so routing is
only offered for the region whose routing module is currently active.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.services.registry import load_registry

# UI travel modes → Valhalla costing models.
_MODE_TO_COSTING = {"walk": "pedestrian", "bike": "bicycle", "car": "auto"}


def decode_polyline(encoded: str, precision: int = 6) -> list[list[float]]:
    """Decode a Valhalla encoded polyline into ``[[lon, lat], ...]`` (GeoJSON
    coordinate order). Valhalla's /route shapes use precision 6 (1e-6)."""
    inv = 10 ** -precision
    coords: list[list[float]] = []
    lat = lon = i = 0
    n = len(encoded)
    while i < n:
        for is_lon in (False, True):
            shift = result = 0
            while True:
                b = ord(encoded[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lon:
                lon += delta
            else:
                lat += delta
        coords.append([lon * inv, lat * inv])
    return coords


def _parse_latlon(raw: str | None) -> tuple[float, float] | None:
    """Parse a ``lat,lon`` string into a validated (lat, lon) tuple, or None."""
    if not raw:
        return None
    parts = raw.replace(";", ",").split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _format_trip(trip: dict) -> dict:
    """Flatten a Valhalla trip into ``{summary, geometry, maneuvers}``."""
    coords: list[list[float]] = []
    maneuvers: list[dict] = []
    for leg in trip.get("legs", []):
        shape = leg.get("shape")
        if shape:
            coords.extend(decode_polyline(shape))
        for m in leg.get("maneuvers", []):
            maneuvers.append({
                "instruction": m.get("instruction", ""),
                "type": m.get("type", 0),
                "length_km": m.get("length", 0.0),
                "time_s": m.get("time", 0.0),
            })
    summary = trip.get("summary", {})
    return {
        "summary": {
            "length_km": summary.get("length", 0.0),
            "time_s": summary.get("time", 0.0),
        },
        "geometry": {"type": "LineString", "coordinates": coords},
        "maneuvers": maneuvers,
    }


def find_active_routing(cfg: Settings, map_id: str):
    """Return the installed + active routing module serving ``map_id``, or None."""
    registry = load_registry(cfg)
    return next(
        (
            m for m in registry.modules
            if m.kind == "routing" and m.routing_for == map_id
            and m.is_installed and m.active
        ),
        None,
    )


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    def _map_region(module_id: str):
        registry = load_registry(cfg)
        return next(
            (m for m in registry.modules
             if m.id == module_id and m.kind == "mbtiles"),
            None,
        )

    @router.get("/map/{module_id}/route")
    async def route(
        request: Request,
        module_id: str,
        from_: str = Query(..., alias="from"),
        to: str = Query(...),
        mode: str = "car",
    ):
        if _map_region(module_id) is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        if find_active_routing(cfg, module_id) is None:
            return JSONResponse(
                {"error": "routing data for this region is not active"},
                status_code=409,
            )
        costing = _MODE_TO_COSTING.get(mode)
        if costing is None:
            return JSONResponse({"error": f"unknown mode: {mode}"}, status_code=400)
        a = _parse_latlon(from_)
        b = _parse_latlon(to)
        if a is None or b is None:
            return JSONResponse(
                {"error": "invalid from/to coordinates"}, status_code=400
            )

        payload = {
            "locations": [
                {"lat": a[0], "lon": a[1]},
                {"lat": b[0], "lon": b[1]},
            ],
            "costing": costing,
            "directions_options": {"units": "kilometers"},
        }
        client: httpx.AsyncClient = request.app.state.http_client
        url = f"http://127.0.0.1:{cfg.valhalla_port}/route"
        try:
            resp = await client.post(url, json=payload)
        except httpx.RequestError:
            return JSONResponse(
                {"error": "routing engine unavailable"}, status_code=502
            )

        if resp.status_code != 200:
            # Valhalla returns 400 with {"error": ...} for no-path / distance limit.
            detail = "no route found"
            try:
                detail = resp.json().get("error", detail)
            except ValueError:
                pass
            return JSONResponse({"error": detail}, status_code=422)

        trip = resp.json().get("trip", {})
        return JSONResponse(_format_trip(trip))

    return router
