from __future__ import annotations
import asyncio
import socket
from app.models.wifi import (
    ConnectRequest,
    WifiAuthError,
    WifiError,
    WifiNetwork,
    WifiNotFoundError,
    WifiStatus,
    WifiTimeoutError,
)

_STA_IFACE = "wlan0"
_NMCLI_TIMEOUT = 45.0


async def _nmcli(
    args: list[str],
    stdin_bytes: bytes | None = None,
    timeout: float = _NMCLI_TIMEOUT,
) -> tuple[int, str, str]:
    """Run nmcli with the given args, return (rc, stdout, stderr).

    Module-level so tests can monkeypatch it. When stdin_bytes is given,
    it is fed to nmcli's stdin (used for password-via-stdin); otherwise
    stdin is DEVNULL.
    """
    proc = await asyncio.create_subprocess_exec(
        "nmcli", *args,
        stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_bytes),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise WifiTimeoutError("nmcli timed out") from exc
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _split_terse(line: str) -> list[str]:
    """Split a terse-mode nmcli line on unescaped ':' boundaries.

    nmcli --terse escapes ':' as '\\:' and '\\' as '\\\\' inside field values.
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            current.append(line[i + 1])
            i += 2
        elif c == ":":
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(c)
            i += 1
    parts.append("".join(current))
    return parts


def _parse_saved(output: str) -> set[str]:
    """Parse `nmcli -t -f NAME,TYPE connection show` into a set of wifi SSIDs."""
    saved: set[str] = set()
    for line in output.splitlines():
        fields = _split_terse(line)
        if len(fields) >= 2 and fields[1] == "802-11-wireless":
            saved.add(fields[0])
    return saved


def _parse_ap_channel(output: str) -> int | None:
    for line in output.splitlines():
        if line.startswith("802-11-wireless.channel:"):
            value = line.split(":", 1)[1].strip()
            if value.isdigit():
                return int(value)
    return None


def _parse_scan(output: str, ap_ssid: str, saved: set[str]) -> tuple[str | None, list[WifiNetwork]]:
    connected_ssid: str | None = None
    seen: set[str] = set()
    networks: list[WifiNetwork] = []
    for line in output.splitlines():
        fields = _split_terse(line)
        if len(fields) < 5:
            continue
        in_use, ssid, signal_s, security, chan_s = fields[:5]
        if not ssid or ssid == ap_ssid or ssid in seen:
            continue
        seen.add(ssid)
        in_use_b = in_use == "*"
        if in_use_b:
            connected_ssid = ssid
        networks.append(WifiNetwork(
            ssid=ssid,
            signal=int(signal_s) if signal_s.lstrip("-").isdigit() else 0,
            security=security,
            channel=int(chan_s) if chan_s.isdigit() else None,
            in_use=in_use_b,
            saved=(ssid in saved),
        ))
    networks.sort(key=lambda n: (not n.in_use, -n.signal))
    return connected_ssid, networks


def _raise_for_rc(rc: int, ssid: str = "", stderr: str = "") -> None:
    """Map nmcli exit codes to typed wifi exceptions. No-op on rc=0."""
    if rc == 0:
        return
    detail = stderr.strip() or f"exit {rc}"
    # nmcli(1) EXIT STATUS:
    #   3  timeout
    #   4  connection activation failed (commonly wrong password)
    #   10 not found
    if rc == 3:
        raise WifiTimeoutError(detail)
    if rc == 4:
        raise WifiAuthError(detail)
    if rc == 10:
        raise WifiNotFoundError(detail)
    raise WifiError(detail)


# ── Public API ────────────────────────────────────────────────────────────────

async def scan_networks() -> WifiStatus:
    ap_ssid = socket.gethostname()

    scan_call = _nmcli([
        "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,CHAN",
        "device", "wifi", "list", "--rescan", "auto", "ifname", _STA_IFACE,
    ])
    saved_call = _nmcli(["-t", "-f", "NAME,TYPE", "connection", "show"])
    ap_call = _nmcli([
        "-t", "-f", "802-11-wireless.channel",
        "connection", "show", ap_ssid,
    ])

    (scan_rc, scan_out, _), (saved_rc, saved_out, _), (ap_rc, ap_out, _) = await asyncio.gather(
        scan_call, saved_call, ap_call,
    )

    if scan_rc == 8:
        raise WifiError("NetworkManager not available")

    saved = _parse_saved(saved_out) if saved_rc == 0 else set()
    ap_channel = _parse_ap_channel(ap_out) if ap_rc == 0 else None
    connected_ssid, networks = _parse_scan(scan_out, ap_ssid, saved)

    return WifiStatus(
        connected_ssid=connected_ssid,
        ap_channel=ap_channel,
        networks=networks,
    )


async def connect(req: ConnectRequest) -> None:
    args = ["device", "wifi", "connect", req.ssid, "ifname", _STA_IFACE]
    stdin_bytes: bytes | None = None

    if req.hidden:
        args += ["hidden", "yes"]

    if req.password:
        args = ["--passwd-file", "/proc/self/fd/0"] + args
        stdin_bytes = f"wifi-sec.psk:{req.password}\n".encode()

    rc, _, err = await _nmcli(args, stdin_bytes=stdin_bytes)
    _raise_for_rc(rc, req.ssid, err)


async def disconnect() -> None:
    rc, _, err = await _nmcli(["device", "disconnect", _STA_IFACE])
    _raise_for_rc(rc, stderr=err)


async def forget(ssid: str) -> None:
    rc, out, err = await _nmcli(["-t", "-f", "NAME,TYPE", "connection", "show"])
    if rc != 0:
        raise WifiError(err.strip() or "failed to list saved connections")
    if ssid not in _parse_saved(out):
        raise WifiNotFoundError(f"no saved network: {ssid}")
    rc, _, err = await _nmcli(["connection", "delete", ssid])
    _raise_for_rc(rc, ssid, err)
