from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeviceType(Enum):
    CHROMECAST = "chromecast"
    APPLETV = "appletv"
    DLNA = "dlna"


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    device_type: DeviceType
    address: str
    port: int = 0
    model: str = ""
    location: str = ""
