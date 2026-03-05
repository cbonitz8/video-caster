from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from video_caster.discovery.device import Device


@dataclass
class PlaybackStatus:
    state: str = "idle"  # idle, buffering, playing, paused, stopped
    current_time: float = 0.0
    duration: float = 0.0
    volume: float = 1.0
    title: str = ""

    @property
    def progress(self) -> float:
        if self.duration <= 0:
            return 0.0
        return min(self.current_time / self.duration, 1.0)


class CastHandler(ABC):
    def __init__(self, device: Device):
        self.device = device

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def play_media(self, url: str, content_type: str = "video/mp4") -> None: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def resume(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def seek(self, position: float) -> None: ...

    @abstractmethod
    async def set_volume(self, level: float) -> None: ...

    @abstractmethod
    async def get_status(self) -> PlaybackStatus: ...
