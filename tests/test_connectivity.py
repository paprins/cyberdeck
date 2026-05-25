from __future__ import annotations
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.services import connectivity as conn
from app.services import notifications as notif


@pytest.fixture(autouse=True)
def _reset_state_cache():
    """Module-level state cache leaks between tests. Wake event must be
    nulled — Event.wait() latches to the first loop that awaits it; pytest
    creates a fresh loop per test."""
    conn._reset_state_cache()
    conn._wake_event = None
    yield


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Subprocess wrapper & NmcliProbe ───────────────────────────────────────────

async def test_nmcli_probe_online(monkeypatch):
    async def fake(timeout=5.0):
        return 0, "full\n", ""
    monkeypatch.setattr(conn, "_nmcli_connectivity", fake)
    assert await conn.NmcliProbe().get_state() == "online"


@pytest.mark.parametrize("nm_output", ["none\n", "limited\n", "portal\n"])
async def test_nmcli_probe_offline_variants(monkeypatch, nm_output):
    async def fake(timeout=5.0):
        return 0, nm_output, ""
    monkeypatch.setattr(conn, "_nmcli_connectivity", fake)
    assert await conn.NmcliProbe().get_state() == "offline"


async def test_nmcli_probe_unknown_on_mystery_output(monkeypatch):
    async def fake(timeout=5.0):
        return 0, "strange\n", ""
    monkeypatch.setattr(conn, "_nmcli_connectivity", fake)
    assert await conn.NmcliProbe().get_state() == "unknown"


async def test_nmcli_probe_unknown_on_binary_missing(monkeypatch):
    async def fake_exec(*args, **kwargs):
        raise FileNotFoundError("nmcli")
    monkeypatch.setattr(conn.asyncio, "create_subprocess_exec", fake_exec)
    assert await conn.NmcliProbe().get_state() == "unknown"


# ── TcpProbe ──────────────────────────────────────────────────────────────────

class _FakeWriter:
    def close(self):
        pass

    async def wait_closed(self):
        pass


async def test_tcp_probe_online_records_latency(monkeypatch):
    async def fake_open(host, port):
        return object(), _FakeWriter()
    monkeypatch.setattr(conn.asyncio, "open_connection", fake_open)
    probe = conn.TcpProbe("1.1.1.1:53")
    assert await probe.get_state() == "online"
    assert conn._state_cache.last_latency_ms is not None
    assert conn._state_cache.last_latency_ms >= 0


async def test_tcp_probe_offline_on_oserror(monkeypatch):
    async def fake_open(host, port):
        raise OSError("connection refused")
    monkeypatch.setattr(conn.asyncio, "open_connection", fake_open)
    assert await conn.TcpProbe("1.1.1.1:53").get_state() == "offline"


async def test_tcp_probe_offline_on_timeout(monkeypatch):
    async def fake_open(host, port):
        await asyncio.sleep(5)
        return object(), _FakeWriter()
    monkeypatch.setattr(conn.asyncio, "open_connection", fake_open)
    monkeypatch.setattr(conn, "_TCP_TIMEOUT", 0.01)
    assert await conn.TcpProbe("1.1.1.1:53").get_state() == "offline"


def test_tcp_probe_parses_target_without_port():
    p = conn.TcpProbe("example.com")
    assert p.host == "example.com"
    assert p.port == 53  # default


def test_tcp_probe_parses_target_with_port():
    p = conn.TcpProbe("example.com:443")
    assert p.host == "example.com"
    assert p.port == 443


# ── CompositeProbe ────────────────────────────────────────────────────────────

class _StaticProbe:
    def __init__(self, state):
        self.state = state

    async def get_state(self):
        return self.state


async def test_composite_returns_first_non_unknown():
    c = conn.CompositeProbe([_StaticProbe("unknown"), _StaticProbe("online")])
    assert await c.get_state() == "online"


async def test_composite_returns_unknown_when_all_unknown():
    c = conn.CompositeProbe([_StaticProbe("unknown"), _StaticProbe("unknown")])
    assert await c.get_state() == "unknown"


async def test_composite_skips_to_fallback_on_first_unknown():
    """First probe (Nmcli) returns unknown → fallback (Tcp) decides."""
    c = conn.CompositeProbe([_StaticProbe("unknown"), _StaticProbe("offline")])
    assert await c.get_state() == "offline"


# ── Preferences ───────────────────────────────────────────────────────────────

def test_effective_connectivity_check_defaults_to_settings(tmp_settings):
    assert notif.effective_connectivity_check(tmp_settings) is False


def test_effective_connectivity_check_uses_override(tmp_settings):
    notif.save_preference(tmp_settings, "connectivity_check", True)
    assert notif.effective_connectivity_check(tmp_settings) is True


def test_has_user_set_false_when_absent(tmp_settings):
    assert notif.has_user_set_connectivity_check(tmp_settings) is False


def test_has_user_set_true_when_present(tmp_settings):
    notif.save_preference(tmp_settings, "connectivity_check", False)
    assert notif.has_user_set_connectivity_check(tmp_settings) is True


# ── State machine ─────────────────────────────────────────────────────────────


async def _run_loop_iterations(tmp_settings, probe, iterations: int = 1):
    """Drive the probe loop for N iterations and cancel.

    The loop's interruptible-sleep uses asyncio.wait_for on the wake event with
    a timeout of cfg.connectivity_poll_seconds. We fire the event N times to
    force N iterations, then cancel.
    """
    task = asyncio.create_task(conn.connectivity_probe_loop(tmp_settings, probe))
    # Allow the bootstrap (which awaits sleep(5)) to be skipped — we monkeypatch
    # asyncio.sleep at the loop level in tests that care; here we just give it
    # a brief moment to settle, then fire iterations.
    await asyncio.sleep(0)
    wake = conn._get_wake_event()
    for _ in range(iterations):
        wake.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.fixture
def _instant_sleep(monkeypatch):
    """Patch asyncio.sleep so the bootstrap 5s wait is instant."""
    real_sleep = asyncio.sleep

    async def fast_sleep(delay, *args, **kwargs):
        if delay >= 1:
            delay = 0
        await real_sleep(delay, *args, **kwargs)
    monkeypatch.setattr(conn.asyncio, "sleep", fast_sleep)
    yield


async def test_loop_sets_online(tmp_settings, _instant_sleep):
    tmp_settings.connectivity_poll_seconds = 60
    notif.save_preference(tmp_settings, "connectivity_check", True)
    await _run_loop_iterations(tmp_settings, _StaticProbe("online"))
    assert conn.get_is_online() is True
    assert conn._state_cache.failure_started_at is None


async def test_loop_offline_starts_failure_clock(tmp_settings, _instant_sleep):
    tmp_settings.connectivity_poll_seconds = 60
    notif.save_preference(tmp_settings, "connectivity_check", True)
    await _run_loop_iterations(tmp_settings, _StaticProbe("offline"))
    assert conn.get_is_online() is False
    assert conn._state_cache.failure_started_at is not None


async def test_loop_recovery_clears_failure_clock(tmp_settings, _instant_sleep):
    """offline → online sequence resets failure_started_at."""
    tmp_settings.connectivity_poll_seconds = 60
    notif.save_preference(tmp_settings, "connectivity_check", True)

    class _Flipping:
        def __init__(self):
            self.calls = 0
        async def get_state(self):
            self.calls += 1
            return "offline" if self.calls == 1 else "online"

    await _run_loop_iterations(tmp_settings, _Flipping(), iterations=2)
    assert conn.get_is_online() is True
    assert conn._state_cache.failure_started_at is None


async def test_loop_auto_disables_after_grace(tmp_settings, monkeypatch, _instant_sleep):
    tmp_settings.connectivity_poll_seconds = 60
    tmp_settings.connectivity_grace_minutes = 10
    notif.save_preference(tmp_settings, "connectivity_check", True)

    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]
    monkeypatch.setattr(conn.time, "monotonic", fake_monotonic)

    class _Offline:
        async def get_state(self):
            return "offline"

    task = asyncio.create_task(conn.connectivity_probe_loop(tmp_settings, _Offline()))
    await asyncio.sleep(0)

    wake = conn._get_wake_event()
    # First tick: failure_started_at gets set to 1000.0
    wake.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Advance past the grace window and fire another tick
    fake_now[0] = 1000.0 + (10 * 60) + 1
    wake.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Auto-disable wrote False to preferences and set auto_disabled_at
    assert notif.effective_connectivity_check(tmp_settings) is False
    assert conn._state_cache.auto_disabled_at is not None
    assert conn._state_cache.failure_started_at is None


async def test_loop_unknown_does_not_advance_failure_clock(tmp_settings, _instant_sleep):
    """offline then unknown: failure_started_at should remain unchanged."""
    tmp_settings.connectivity_poll_seconds = 60
    notif.save_preference(tmp_settings, "connectivity_check", True)

    class _OfflineThenUnknown:
        def __init__(self):
            self.calls = 0
        async def get_state(self):
            self.calls += 1
            return "offline" if self.calls == 1 else "unknown"

    await _run_loop_iterations(tmp_settings, _OfflineThenUnknown(), iterations=2)
    # Failure clock was set on offline iteration and not touched on unknown
    assert conn._state_cache.failure_started_at is not None
    assert conn.get_is_online() is None


async def test_loop_skips_probe_when_disabled(tmp_settings, _instant_sleep):
    """When connectivity_check is off, probe is never called and is_online is None."""
    tmp_settings.connectivity_poll_seconds = 60
    notif.save_preference(tmp_settings, "connectivity_check", False)

    class _Counter:
        def __init__(self):
            self.calls = 0
        async def get_state(self):
            self.calls += 1
            return "online"

    counter = _Counter()
    # Bootstrap also calls probe — pre-seed the preferences so bootstrap is skipped.
    # (has_user_set returns True because the key exists.)
    await _run_loop_iterations(tmp_settings, counter, iterations=2)
    assert conn.get_is_online() is None
    assert counter.calls == 0


async def test_bootstrap_auto_enables_when_online(tmp_settings, _instant_sleep):
    """First boot, no prefs, probe returns online → connectivity_check becomes True."""
    assert notif.has_user_set_connectivity_check(tmp_settings) is False

    task = asyncio.create_task(
        conn.connectivity_probe_loop(tmp_settings, _StaticProbe("online"))
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert notif.has_user_set_connectivity_check(tmp_settings) is True
    assert notif.effective_connectivity_check(tmp_settings) is True


async def test_bootstrap_does_not_enable_when_offline(tmp_settings, _instant_sleep):
    """First boot, no prefs, probe returns offline → preferences untouched."""
    task = asyncio.create_task(
        conn.connectivity_probe_loop(tmp_settings, _StaticProbe("offline"))
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert notif.has_user_set_connectivity_check(tmp_settings) is False


# ── /api/settings/connectivity-check endpoint ────────────────────────────────

async def test_set_connectivity_check_returns_204(client):
    r = await client.post("/api/settings/connectivity-check", json={"enabled": True})
    assert r.status_code == 204


async def test_set_connectivity_check_persists(client, tmp_settings):
    assert notif.effective_connectivity_check(tmp_settings) is False
    r = await client.post("/api/settings/connectivity-check", json={"enabled": True})
    assert r.status_code == 204
    assert notif.effective_connectivity_check(tmp_settings) is True


async def test_set_connectivity_check_triggers_immediate_probe(client):
    r = await client.post("/api/settings/connectivity-check", json={"enabled": True})
    assert r.status_code == 204
    assert conn._get_wake_event().is_set() is True


async def test_set_connectivity_check_disable_does_not_trigger_probe(client):
    r = await client.post("/api/settings/connectivity-check", json={"enabled": False})
    assert r.status_code == 204
    assert conn._get_wake_event().is_set() is False


# ── /api/system payload ──────────────────────────────────────────────────────

async def test_system_endpoint_includes_is_online(client):
    r = await client.get("/api/system")
    data = r.json()
    assert "is_online" in data
    assert data["is_online"] is None or isinstance(data["is_online"], bool)


async def test_system_payload_is_online_reflects_cache(client):
    conn._state_cache.is_online = True
    r = await client.get("/api/system")
    assert r.json()["is_online"] is True

    conn._state_cache.is_online = False
    r = await client.get("/api/system")
    assert r.json()["is_online"] is False


async def test_system_payload_connectivity_shape(client, tmp_settings):
    r = await client.get("/api/system")
    c = r.json()["connectivity"]
    for key in ("last_state", "last_latency_ms", "last_checked_at", "target"):
        assert key in c
    assert c["target"] == tmp_settings.connectivity_target


async def test_system_payload_connectivity_reflects_cache(client):
    conn._state_cache.last_state = "online"
    conn._state_cache.last_latency_ms = 42
    conn._state_cache.last_checked_at = 1700000000.0
    r = await client.get("/api/system")
    c = r.json()["connectivity"]
    assert c["last_state"] == "online"
    assert c["last_latency_ms"] == 42
    assert c["last_checked_at"] == 1700000000.0


# ── Snapshot integration ─────────────────────────────────────────────────────

def test_snapshot_includes_connectivity_check(tmp_settings):
    from app.models.registry import Registry
    from app.services.registry import save_registry
    save_registry(tmp_settings, Registry(modules=[]))
    snap = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert snap.connectivity_check is False
    assert snap.connectivity_grace_minutes == 10
    assert snap.connectivity_check_auto_disabled_at is None


def test_snapshot_auto_disabled_at_propagates_from_cache(tmp_settings):
    from app.models.registry import Registry
    from app.services.registry import save_registry
    save_registry(tmp_settings, Registry(modules=[]))
    conn._state_cache.auto_disabled_at = 1234567.0
    snap = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert snap.connectivity_check_auto_disabled_at == 1234567.0
