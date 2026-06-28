from __future__ import annotations
import httpx
import pytest

import app.services.diagnostics as diag


@pytest.fixture
def app(tmp_settings):
    from app.main import create_app
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── read_diagnostics ──────────────────────────────────────────────────────────

async def _stub_probes_ok(monkeypatch):
    async def fake_probe(name, port, client):
        return diag.ServiceHealth(
            name=name, url=f"http://localhost:{port}/",
            state="ok", status_code=200, latency_ms=5,
        )
    monkeypatch.setattr(diag, "_probe", fake_probe)


async def test_read_diagnostics_returns_all_fields(tmp_settings, monkeypatch):
    await _stub_probes_ok(monkeypatch)
    d = await diag.read_diagnostics(tmp_settings)
    assert isinstance(d.active_modules, int)
    assert isinstance(d.total_modules, int)
    assert isinstance(d.updates_available, int)
    assert len(d.services) == 4
    assert {s.name for s in d.services} == {"kiwix", "mbtileserver", "valhalla", "cyberdeck"}


async def test_read_diagnostics_probes_use_settings_ports(tmp_settings, monkeypatch):
    seen: list[tuple[str, int]] = []

    async def fake_probe(name, port, client):
        seen.append((name, port))
        return diag.ServiceHealth(name=name, url="", state="ok", status_code=200, latency_ms=1)

    monkeypatch.setattr(diag, "_probe", fake_probe)
    await diag.read_diagnostics(tmp_settings)
    assert sorted(seen) == [
        ("cyberdeck", tmp_settings.app_port),
        ("kiwix", tmp_settings.kiwix_port),
        ("mbtileserver", tmp_settings.mbtiles_port),
        ("valhalla", tmp_settings.valhalla_port),
    ]


async def test_read_diagnostics_marks_service_down_on_request_error(tmp_settings, monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, timeout=None):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(diag.httpx, "AsyncClient", lambda *a, **kw: FakeClient())
    d = await diag.read_diagnostics(tmp_settings)
    assert all(s.state == "down" for s in d.services)
    assert all(s.latency_ms is None for s in d.services)
    assert all(s.status_code is None for s in d.services)


async def test_read_diagnostics_marks_service_down_on_5xx(tmp_settings, monkeypatch):
    class FakeResponse:
        status_code = 503

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(diag.httpx, "AsyncClient", lambda *a, **kw: FakeClient())
    d = await diag.read_diagnostics(tmp_settings)
    assert all(s.state == "down" for s in d.services)
    assert all(s.status_code == 503 for s in d.services)


# ── GET /api/diagnostics ──────────────────────────────────────────────────────

async def test_diagnostics_endpoint_returns_200(client, monkeypatch):
    await _stub_probes_ok(monkeypatch)
    r = await client.get("/api/diagnostics")
    assert r.status_code == 200


async def test_diagnostics_endpoint_returns_all_keys(client, monkeypatch):
    await _stub_probes_ok(monkeypatch)
    r = await client.get("/api/diagnostics")
    body = r.json()
    for key in (
        "uptime_s", "brightness_pct",
        "storage_used_bytes", "storage_free_bytes", "storage_total_bytes",
        "updates_available", "firmware_version",
        "active_modules", "total_modules",
        "loadavg_1m", "loadavg_5m",
        "mem_total_kb", "mem_available_kb",
        "temp_c", "services",
    ):
        assert key in body, f"missing {key}"
    assert len(body["services"]) == 4


# ── GET /settings/status ──────────────────────────────────────────────────────

async def test_settings_status_route_returns_html(client, monkeypatch):
    await _stub_probes_ok(monkeypatch)
    r = await client.get("/settings/status")
    assert r.status_code == 200
    assert "DEVICE_STATUS" in r.text
    assert "STATUS" in r.text  # sidebar nav link
