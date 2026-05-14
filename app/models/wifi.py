from __future__ import annotations
from pydantic import BaseModel


class WifiNetwork(BaseModel):
    ssid: str
    signal: int
    security: str
    channel: int | None
    in_use: bool
    saved: bool


class WifiStatus(BaseModel):
    connected_ssid: str | None
    ap_channel: int | None
    networks: list[WifiNetwork]


class ConnectRequest(BaseModel):
    ssid: str
    password: str | None = None
    hidden: bool = False


class ForgetRequest(BaseModel):
    ssid: str


class WifiError(RuntimeError):
    """Base class for wifi service failures mapped to HTTP statuses."""


class WifiAuthError(WifiError):
    """nmcli reported an authentication failure (typically wrong password)."""


class WifiTimeoutError(WifiError):
    """nmcli operation exceeded its timeout."""


class WifiNotFoundError(WifiError):
    """SSID or saved profile not found."""
