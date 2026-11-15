from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeviceType(Enum):
    CHROMECAST = "chromecast"
    APPLETV = "appletv"
    DLNA = "dlna"


@dataclass
class Device:
    name: str
    device_type: DeviceType
    address: str
    port: int = 0
    model: str = ""
    protocol_config: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.device_type.value}:{self.address}:{self.port}"
