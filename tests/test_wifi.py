from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
import app.services.wifi as wifi_svc
from app.models.wifi import (
    ConnectRequest,
    WifiAuthError,
    WifiNetwork,
    WifiNotFoundError,
    WifiStatus,
    WifiTimeoutError,
)


# ── Test plumbing ─────────────────────────────────────────────────────────────


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _fake_nmcli(responses):
    """Return an async _nmcli stub that pops scripted (rc, stdout, stderr) tuples.

    `responses` may also be a single tuple, in which case every call returns it.
    Calls are recorded on the returned function's `calls` list as
    (args, stdin_bytes) for assertions.
    """
    if isinstance(responses, tuple):
        responses_list = None
        single = responses
    else:
        responses_list = list(responses)
        single = None

    async def fake(args, stdin_bytes=None, timeout=None):
        fake.calls.append((args, stdin_bytes))
        if responses_list is not None:
            return responses_list.pop(0)
        return single

    fake.calls = []
    return fake


# ── _split_terse parser ───────────────────────────────────────────────────────


def test_split_terse_plain():
    assert wifi_svc._split_terse("a:b:c") == ["a", "b", "c"]


def test_split_terse_unescapes_colon():
    # nmcli encodes literal ":" as "\:"
    assert wifi_svc._split_terse(r"foo\:bar:baz") == ["foo:bar", "baz"]


def test_split_terse_unescapes_backslash():
    assert wifi_svc._split_terse(r"foo\\bar:baz") == [r"foo\bar", "baz"]


def test_split_terse_empty_field():
    assert wifi_svc._split_terse(":x:") == ["", "x", ""]


# ── _parse_scan ───────────────────────────────────────────────────────────────


def test_parse_scan_basic():
    out = "*:HomeNet:75:WPA2:6\n :Other:55:WPA2:11\n"
    connected, networks = wifi_svc._parse_scan(out, "ap-host", set())
    assert connected == "HomeNet"
    assert [n.ssid for n in networks] == ["HomeNet", "Other"]
    assert networks[0].in_use is True
    assert networks[0].channel == 6
    assert networks[1].signal == 55


def test_parse_scan_filters_ap_ssid():
    out = "*:HomeNet:75:WPA2:6\n :cyberdeck-two:80:WPA2:6\n"
    _, networks = wifi_svc._parse_scan(out, "cyberdeck-two", set())
    assert [n.ssid for n in networks] == ["HomeNet"]


def test_parse_scan_filters_empty_ssid():
    out = "*:HomeNet:75:WPA2:6\n :  :60:WPA2:6\n ::40:WPA2:6\n"
    _, networks = wifi_svc._parse_scan(out, "ap", set())
    assert [n.ssid for n in networks] == ["HomeNet", "  "]
    # Truly empty SSID is dropped; a whitespace-only SSID is kept (nmcli quirk)


def test_parse_scan_dedupes_by_ssid_first_wins():
    out = " :Repeated:90:WPA2:1\n :Repeated:50:WPA2:6\n"
    _, networks = wifi_svc._parse_scan(out, "ap", set())
    assert len(networks) == 1
    assert networks[0].signal == 90


def test_parse_scan_marks_saved():
    out = " :Known:70:WPA2:6\n :Unknown:65:WPA2:11\n"
    _, networks = wifi_svc._parse_scan(out, "ap", {"Known"})
    by_ssid = {n.ssid: n for n in networks}
    assert by_ssid["Known"].saved is True
    assert by_ssid["Unknown"].saved is False


def test_parse_scan_open_network_empty_security():
    out = " :OpenNet:50::6\n"
    _, networks = wifi_svc._parse_scan(out, "ap", set())
    assert networks[0].security == ""


def test_parse_scan_sorts_in_use_first_then_signal():
    out = " :LowSignal:30:WPA2:6\n :HighSignal:80:WPA2:6\n*:Active:50:WPA2:6\n"
    _, networks = wifi_svc._parse_scan(out, "ap", set())
    assert [n.ssid for n in networks] == ["Active", "HighSignal", "LowSignal"]


def test_parse_scan_handles_escaped_colon_in_ssid():
    out = r" :Foo\:Bar:60:WPA2:6" + "\n"
    _, networks = wifi_svc._parse_scan(out, "ap", set())
    assert networks[0].ssid == "Foo:Bar"


# ── _parse_saved ──────────────────────────────────────────────────────────────


def test_parse_saved_filters_to_wireless():
    out = "MyHome:802-11-wireless\nWired:802-3-ethernet\nOther:802-11-wireless\n"
    assert wifi_svc._parse_saved(out) == {"MyHome", "Other"}


# ── _parse_ap_channel ─────────────────────────────────────────────────────────


def test_parse_ap_channel_basic():
    assert wifi_svc._parse_ap_channel("802-11-wireless.channel:6\n") == 6


def test_parse_ap_channel_returns_none_on_empty():
    assert wifi_svc._parse_ap_channel("") is None


def test_parse_ap_channel_returns_none_on_unset():
    # nmcli prints empty value when channel is unset
    assert wifi_svc._parse_ap_channel("802-11-wireless.channel:\n") is None


# ── connect: command construction ─────────────────────────────────────────────


async def test_connect_open_network_no_stdin(monkeypatch):
    fake = _fake_nmcli((0, "", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    await wifi_svc.connect(ConnectRequest(ssid="OpenNet", password=None))
    args, stdin = fake.calls[0]
    assert "--passwd-file" not in args
    assert stdin is None
    assert "OpenNet" in args


async def test_connect_secured_passes_password_on_stdin(monkeypatch):
    fake = _fake_nmcli((0, "", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    await wifi_svc.connect(ConnectRequest(ssid="HomeNet", password="s3cret"))
    args, stdin = fake.calls[0]
    assert args[:2] == ["--passwd-file", "/proc/self/fd/0"]
    assert "s3cret" not in args
    assert stdin == b"wifi-sec.psk:s3cret\n"


async def test_connect_hidden_adds_hidden_yes(monkeypatch):
    fake = _fake_nmcli((0, "", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    await wifi_svc.connect(ConnectRequest(ssid="HiddenOne", password="x", hidden=True))
    args, _ = fake.calls[0]
    # Last two trailing args should include hidden yes
    assert "hidden" in args
    idx = args.index("hidden")
    assert args[idx + 1] == "yes"


async def test_connect_uses_wlan0_ifname(monkeypatch):
    fake = _fake_nmcli((0, "", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    await wifi_svc.connect(ConnectRequest(ssid="X", password=None))
    args, _ = fake.calls[0]
    assert "ifname" in args and args[args.index("ifname") + 1] == "wlan0"


# ── connect: error mapping ────────────────────────────────────────────────────


async def test_connect_raises_auth_error_on_rc_4(monkeypatch):
    fake = _fake_nmcli((4, "", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    with pytest.raises(WifiAuthError):
        await wifi_svc.connect(ConnectRequest(ssid="X", password="wrong"))


async def test_connect_raises_timeout_on_rc_3(monkeypatch):
    fake = _fake_nmcli((3, "", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    with pytest.raises(WifiTimeoutError):
        await wifi_svc.connect(ConnectRequest(ssid="X", password=None))


async def test_connect_raises_not_found_on_rc_10(monkeypatch):
    fake = _fake_nmcli((10, "", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    with pytest.raises(WifiNotFoundError):
        await wifi_svc.connect(ConnectRequest(ssid="Missing", password=None))


# ── disconnect ────────────────────────────────────────────────────────────────


async def test_disconnect_calls_device_disconnect(monkeypatch):
    fake = _fake_nmcli((0, "", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    await wifi_svc.disconnect()
    args, _ = fake.calls[0]
    assert args == ["device", "disconnect", "wlan0"]


# ── forget ────────────────────────────────────────────────────────────────────


async def test_forget_deletes_matching_connection(monkeypatch):
    fake = _fake_nmcli([
        (0, "HomeNet:802-11-wireless\nOther:802-11-wireless\nWired:802-3-ethernet\n", ""),
        (0, "", ""),
    ])
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    await wifi_svc.forget("HomeNet")
    assert fake.calls[1][0] == ["connection", "delete", "HomeNet"]


async def test_forget_raises_not_found_when_no_match(monkeypatch):
    fake = _fake_nmcli((0, "Other:802-11-wireless\n", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    with pytest.raises(WifiNotFoundError):
        await wifi_svc.forget("Missing")


async def test_forget_raises_not_found_when_only_ethernet(monkeypatch):
    fake = _fake_nmcli((0, "MyName:802-3-ethernet\n", ""))
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    with pytest.raises(WifiNotFoundError):
        await wifi_svc.forget("MyName")


# ── scan_networks integration (through public API) ────────────────────────────


async def test_scan_networks_returns_status(monkeypatch):
    fake = _fake_nmcli([
        (0, "*:HomeNet:75:WPA2:6\n :Other:55:WPA2:11\n", ""),  # scan
        (0, "HomeNet:802-11-wireless\n", ""),                   # saved
        (0, "802-11-wireless.channel:6\n", ""),                 # ap channel
    ])
    monkeypatch.setattr(wifi_svc, "_nmcli", fake)
    status = await wifi_svc.scan_networks()
    assert isinstance(status, WifiStatus)
    assert status.connected_ssid == "HomeNet"
    assert status.ap_channel == 6
    assert {n.ssid for n in status.networks} == {"HomeNet", "Other"}


# ── Router endpoints ──────────────────────────────────────────────────────────


async def test_get_networks_returns_200(client, monkeypatch):
    async def fake_scan():
        return WifiStatus(connected_ssid=None, ap_channel=6, networks=[])
    monkeypatch.setattr(wifi_svc, "scan_networks", fake_scan)
    r = await client.get("/api/wifi/networks")
    assert r.status_code == 200
    assert r.json() == {"connected_ssid": None, "ap_channel": 6, "networks": []}


async def test_get_networks_returns_500_on_wifi_error(client, monkeypatch):
    async def fake_scan():
        raise wifi_svc.WifiError("nm down")
    monkeypatch.setattr(wifi_svc, "scan_networks", fake_scan)
    r = await client.get("/api/wifi/networks")
    assert r.status_code == 500
    assert "error" in r.json()


async def test_post_connect_returns_204(client, monkeypatch):
    seen = []
    async def fake_connect(req):
        seen.append(req)
    monkeypatch.setattr(wifi_svc, "connect", fake_connect)
    r = await client.post("/api/wifi/connect", json={"ssid": "X", "password": "p"})
    assert r.status_code == 204
    assert seen[0].ssid == "X"


async def test_post_connect_returns_401_on_auth_error(client, monkeypatch):
    async def fake_connect(req):
        raise WifiAuthError("wrong password")
    monkeypatch.setattr(wifi_svc, "connect", fake_connect)
    r = await client.post("/api/wifi/connect", json={"ssid": "X", "password": "p"})
    assert r.status_code == 401


async def test_post_connect_returns_408_on_timeout(client, monkeypatch):
    async def fake_connect(req):
        raise WifiTimeoutError("timeout")
    monkeypatch.setattr(wifi_svc, "connect", fake_connect)
    r = await client.post("/api/wifi/connect", json={"ssid": "X", "password": "p"})
    assert r.status_code == 408


async def test_post_connect_returns_404_when_ssid_unknown(client, monkeypatch):
    async def fake_connect(req):
        raise WifiNotFoundError("not found")
    monkeypatch.setattr(wifi_svc, "connect", fake_connect)
    r = await client.post("/api/wifi/connect", json={"ssid": "X", "password": "p"})
    assert r.status_code == 404


async def test_post_connect_rejects_missing_ssid(client):
    r = await client.post("/api/wifi/connect", json={"password": "p"})
    assert r.status_code == 422


async def test_post_disconnect_returns_204(client, monkeypatch):
    async def fake_disc():
        pass
    monkeypatch.setattr(wifi_svc, "disconnect", fake_disc)
    r = await client.post("/api/wifi/disconnect")
    assert r.status_code == 204


async def test_post_forget_returns_204(client, monkeypatch):
    seen = []
    async def fake_forget(ssid):
        seen.append(ssid)
    monkeypatch.setattr(wifi_svc, "forget", fake_forget)
    r = await client.post("/api/wifi/forget", json={"ssid": "X"})
    assert r.status_code == 204
    assert seen == ["X"]


async def test_post_forget_returns_404_when_unknown(client, monkeypatch):
    async def fake_forget(ssid):
        raise WifiNotFoundError("nope")
    monkeypatch.setattr(wifi_svc, "forget", fake_forget)
    r = await client.post("/api/wifi/forget", json={"ssid": "X"})
    assert r.status_code == 404
