from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.registry import Module, Registry
from app.routers.routing import _parse_latlon, decode_polyline
from app.services.registry import save_registry


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _seed(tmp_settings, *, routing=True, routing_active=True):
    mods = [
        Module(
            id="netherlands", display_name="Netherlands", category="navigation",
            description="NL", latest_version="1", size_gb=0.8,
            kind="mbtiles", checksum="sha256:abc", active=True,
        )
    ]
    if routing:
        mods.append(Module(
            id="netherlands-routing", display_name="NL Routing", category="navigation",
            description="NL routes", latest_version="1", size_gb=0.5,
            kind="routing", checksum="sha256:def", routing_for="netherlands",
            installed_version="1", active=routing_active,
        ))
    save_registry(tmp_settings, Registry(modules=mods))


class _FakeResp:
    def __init__(self, status: int, data: dict):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


def _mock_valhalla(app, *, status=200, data=None, raises=None):
    """Replace the shared http client's POST with a stub; return a dict that
    captures the request the route endpoint sent to Valhalla."""
    captured: dict = {}

    async def fake_post(url, json=None):
        captured["url"] = url
        captured["json"] = json
        if raises is not None:
            raise raises
        return _FakeResp(status, data or {})

    app.state.http_client.post = fake_post
    return captured


_TRIP = {
    "summary": {"length": 12.5, "time": 900},
    "legs": [{
        "shape": "g@S",
        "maneuvers": [
            {"instruction": "Drive north.", "type": 1, "length": 12.5, "time": 900},
            {"instruction": "You have arrived.", "type": 4, "length": 0.0, "time": 0.0},
        ],
    }],
}


# ── decode_polyline ────────────────────────────────────────────────────────

def test_decode_polyline_known_vector():
    # Hand-encoded single point lat=2e-5, lon=1e-5 at precision 6.
    coords = decode_polyline("g@S")
    assert len(coords) == 1
    lon, lat = coords[0]
    assert lon == pytest.approx(1e-5)
    assert lat == pytest.approx(2e-5)


def test_decode_polyline_roundtrip():
    def encode(coords, precision=6):
        factor = 10 ** precision
        out = []
        prev_lat = prev_lon = 0
        for lon, lat in coords:
            ilat, ilon = round(lat * factor), round(lon * factor)
            for cur, prev in ((ilat, prev_lat), (ilon, prev_lon)):
                d = cur - prev
                d = ~(d << 1) if d < 0 else (d << 1)
                while d >= 0x20:
                    out.append(chr((0x20 | (d & 0x1F)) + 63))
                    d >>= 5
                out.append(chr(d + 63))
            prev_lat, prev_lon = ilat, ilon
        return "".join(out)

    original = [[4.895168, 52.370216], [4.477733, 51.924420], [5.121420, 52.090736]]
    decoded = decode_polyline(encode(original))
    assert len(decoded) == len(original)
    for (lon, lat), (olon, olat) in zip(decoded, original):
        assert lon == pytest.approx(olon, abs=1e-6)
        assert lat == pytest.approx(olat, abs=1e-6)


# ── _parse_latlon ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("52.37, 4.89", (52.37, 4.89)),
    ("52.37,4.89", (52.37, 4.89)),
    ("-33.9, 18.4", (-33.9, 18.4)),
    ("52.37; 4.89", (52.37, 4.89)),
])
def test_parse_latlon_valid(raw, expected):
    assert _parse_latlon(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "abc", "52.37", "91, 0", "0, 200", "1,2,3"])
def test_parse_latlon_invalid(raw):
    assert _parse_latlon(raw) is None


# ── /map/{id}/route ────────────────────────────────────────────────────────

async def test_route_success(client, app, tmp_settings):
    _seed(tmp_settings)
    captured = _mock_valhalla(app, data={"trip": _TRIP})
    r = await client.get("/map/netherlands/route?from=52.37,4.89&to=51.92,4.47&mode=car")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["length_km"] == 12.5
    assert body["summary"]["time_s"] == 900
    assert body["geometry"]["type"] == "LineString"
    assert len(body["maneuvers"]) == 2
    assert body["maneuvers"][0]["instruction"] == "Drive north."
    # The request reached Valhalla with the right locations + costing.
    assert captured["json"]["costing"] == "auto"
    assert captured["json"]["locations"] == [
        {"lat": 52.37, "lon": 4.89}, {"lat": 51.92, "lon": 4.47},
    ]


@pytest.mark.parametrize("mode,costing", [
    ("walk", "pedestrian"), ("bike", "bicycle"), ("car", "auto"),
])
async def test_route_mode_to_costing(client, app, tmp_settings, mode, costing):
    _seed(tmp_settings)
    captured = _mock_valhalla(app, data={"trip": _TRIP})
    r = await client.get(f"/map/netherlands/route?from=52.37,4.89&to=51.92,4.47&mode={mode}")
    assert r.status_code == 200
    assert captured["json"]["costing"] == costing


async def test_route_unknown_region_404(client, tmp_settings):
    save_registry(tmp_settings, Registry())
    r = await client.get("/map/missing/route?from=52.37,4.89&to=51.92,4.47&mode=car")
    assert r.status_code == 404


async def test_route_no_active_routing_409(client, tmp_settings):
    _seed(tmp_settings, routing=False)
    r = await client.get("/map/netherlands/route?from=52.37,4.89&to=51.92,4.47&mode=car")
    assert r.status_code == 409


async def test_route_inactive_routing_409(client, tmp_settings):
    _seed(tmp_settings, routing_active=False)
    r = await client.get("/map/netherlands/route?from=52.37,4.89&to=51.92,4.47&mode=car")
    assert r.status_code == 409


async def test_route_invalid_mode_400(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.get("/map/netherlands/route?from=52.37,4.89&to=51.92,4.47&mode=teleport")
    assert r.status_code == 400


async def test_route_invalid_coords_400(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.get("/map/netherlands/route?from=nope&to=51.92,4.47&mode=car")
    assert r.status_code == 400


async def test_route_valhalla_down_502(client, app, tmp_settings):
    _seed(tmp_settings)
    _mock_valhalla(app, raises=httpx.RequestError("connection refused"))
    r = await client.get("/map/netherlands/route?from=52.37,4.89&to=51.92,4.47&mode=car")
    assert r.status_code == 502


async def test_route_valhalla_no_path_422(client, app, tmp_settings):
    _seed(tmp_settings)
    _mock_valhalla(app, status=400, data={"error": "No path could be found between locations"})
    r = await client.get("/map/netherlands/route?from=52.37,4.89&to=51.92,4.47&mode=car")
    assert r.status_code == 422
    assert "No path" in r.json()["error"]
