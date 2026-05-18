from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from app.config import Settings

log = logging.getLogger(__name__)

ConnectivityState = Literal["online", "offline", "unknown"]

_NMCLI_TIMEOUT = 5.0
_TCP_TIMEOUT = 1.0


# ── Subprocess wrapper (mirrors wifi.py:_nmcli) ───────────────────────────────

async def _nmcli_connectivity(timeout: float = _NMCLI_TIMEOUT) -> tuple[int, str, str]:
    """Run `nmcli networking connectivity`, return (rc, stdout, stderr).

    Module-level so tests can monkeypatch it. Missing binary or timeout returns
    a sentinel (1, "", "") which the caller maps to "unknown".
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "nmcli", "networking", "connectivity",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 1, "", ""
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, "", ""
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


# ── Probes ────────────────────────────────────────────────────────────────────

class ConnectivityProbe(Protocol):
    async def get_state(self) -> ConnectivityState: ...


class NmcliProbe:
    """Reads NetworkManager's own connectivity state. Zero packets from us."""

    async def get_state(self) -> ConnectivityState:
        _, stdout, _ = await _nmcli_connectivity()
        result = stdout.strip().lower()
        if result == "full":
            return "online"
        if result in ("none", "limited", "portal"):
            return "offline"
        return "unknown"


class TcpProbe:
    """Async TCP connect to host:port. Records last_latency_ms on success."""

    def __init__(self, target: str) -> None:
        host, sep, port_s = target.rpartition(":")
        # If no ":" found, rpartition puts the whole string in port_s.
        if not sep:
            host = target
            port_s = ""
        self.host = host or target
        self.port = int(port_s) if port_s.isdigit() else 53

    async def get_state(self) -> ConnectivityState:
        started = time.monotonic()
        writer = None
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=_TCP_TIMEOUT,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            _state_cache.last_latency_ms = latency_ms
            return "online"
        except (OSError, asyncio.TimeoutError):
            return "offline"
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass


class CompositeProbe:
    """Tries probes in order, returns first non-'unknown' result."""

    def __init__(self, probes: list[ConnectivityProbe]) -> None:
        self._probes = probes

    async def get_state(self) -> ConnectivityState:
        for probe in self._probes:
            result = await probe.get_state()
            if result != "unknown":
                return result
        return "unknown"


def make_default_probe(cfg: Settings) -> ConnectivityProbe:
    """Factory used by lifespan: nmcli first, TCP probe as fallback."""
    return CompositeProbe([NmcliProbe(), TcpProbe(cfg.connectivity_target)])


# ── In-memory state cache ─────────────────────────────────────────────────────

@dataclass
class _ConnectivityCache:
    is_online: bool | None = None
    last_state: ConnectivityState = "unknown"
    failure_started_at: float | None = None
    last_checked_at: float | None = None
    last_latency_ms: int | None = None
    auto_disabled_at: float | None = None


_state_cache = _ConnectivityCache()


def _reset_state_cache() -> None:
    """Reset all cache fields. Called by autouse fixture in tests."""
    _state_cache.is_online = None
    _state_cache.last_state = "unknown"
    _state_cache.failure_started_at = None
    _state_cache.last_checked_at = None
    _state_cache.last_latency_ms = None
    _state_cache.auto_disabled_at = None


def get_is_online() -> bool | None:
    return _state_cache.is_online


def get_auto_disabled_at() -> float | None:
    return _state_cache.auto_disabled_at


def get_connectivity_snapshot() -> dict:
    """Cheap read for diagnostics — no subprocess, no I/O."""
    return {
        "last_state": _state_cache.last_state,
        "last_latency_ms": _state_cache.last_latency_ms,
        "last_checked_at": _state_cache.last_checked_at,
    }


# ── Immediate re-probe event ──────────────────────────────────────────────────

# Lazy construction is load-bearing: asyncio.Event.wait() latches onto the
# first loop that awaits it. Pytest spins up a fresh loop per test, so a
# module-level Event constructed once at import time would raise RuntimeError
# on the second test's wait(). Lazy init lets _reset_state_cache() (autouse)
# clear the cached Event between tests.
_wake_event: asyncio.Event | None = None


def _get_wake_event() -> asyncio.Event:
    global _wake_event
    if _wake_event is None:
        _wake_event = asyncio.Event()
    return _wake_event


async def request_immediate_probe() -> None:
    """Signal the probe loop to fire on the next event-loop tick."""
    _get_wake_event().set()


# ── Background probe loop ─────────────────────────────────────────────────────

async def connectivity_probe_loop(cfg: Settings, probe: ConnectivityProbe) -> None:
    """Lifespan background task. Cancelled cleanly on shutdown."""
    # Deferred imports to break circular reference with notifications.py.
    from app.services.notifications import (
        effective_connectivity_check,
        has_user_set_connectivity_check,
        save_preference,
    )

    wake = _get_wake_event()

    # Let NetworkManager settle after boot before the first probe.
    try:
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        raise

    # ── Bootstrap: auto-enable if internet is reachable and user has not decided ──
    if not has_user_set_connectivity_check(cfg):
        try:
            result = await probe.get_state()
        except Exception:
            log.exception("connectivity bootstrap probe raised")
            result = "unknown"
        if result == "online":
            save_preference(cfg, "connectivity_check", True)
            # Populate cache so the UI reflects the just-confirmed state without
            # waiting up to connectivity_poll_seconds for the first loop tick.
            _state_cache.is_online = True
            _state_cache.last_state = "online"
            _state_cache.last_checked_at = time.time()
            wake.set()

    # ── Main loop ──
    while True:
        try:
            try:
                await asyncio.wait_for(
                    wake.wait(),
                    timeout=float(cfg.connectivity_poll_seconds),
                )
            except asyncio.TimeoutError:
                pass
            wake.clear()

            if not effective_connectivity_check(cfg):
                _state_cache.is_online = None
                _state_cache.failure_started_at = None
                continue

            try:
                result = await probe.get_state()
            except Exception:
                log.exception("connectivity probe raised")
                result = "unknown"

            _state_cache.last_state = result
            _state_cache.last_checked_at = time.time()

            if result == "online":
                _state_cache.is_online = True
                _state_cache.failure_started_at = None
            elif result == "offline":
                _state_cache.is_online = False
                if _state_cache.failure_started_at is None:
                    _state_cache.failure_started_at = time.monotonic()
                else:
                    elapsed = time.monotonic() - _state_cache.failure_started_at
                    if elapsed >= cfg.connectivity_grace_minutes * 60:
                        save_preference(cfg, "connectivity_check", False)
                        _state_cache.auto_disabled_at = time.time()
                        _state_cache.failure_started_at = None
            else:
                # "unknown" — do not advance the failure clock.
                _state_cache.is_online = None

        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("connectivity_probe_loop iteration failed")
