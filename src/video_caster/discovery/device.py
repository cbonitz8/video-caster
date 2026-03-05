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
    def display_name(self) -> str:
        icon = "\u25ce" if self.device_type == DeviceType.CHROMECAST else "\uf8ff"
        # Use a safe fallback icon for Apple TV since  may not render
        if self.device_type == DeviceType.APPLETV:
            icon = "\u25c6"
        elif self.device_type == DeviceType.DLNA:
            icon = "\u25a8"
        return f"{icon} {self.name}"

    @property
    def id(self) -> str:
        return f"{self.device_type.value}:{self.address}:{self.port}"
