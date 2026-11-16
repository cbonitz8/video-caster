from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Awaitable, Callable

from video_caster.discovery.device import Device


@dataclass
class PlaybackStatus:
    state: str = "idle"  # idle, buffering, playing, paused, stopped
    current_time: float = 0.0
    duration: float = 0.0
    volume: float = 1.0

    @property
    def progress(self) -> float:
        if self.duration <= 0:
            return 0.0
        return min(self.current_time / self.duration, 1.0)


@dataclass(frozen=True)
class Media:
    url: str
    content_type: str
    title: str
    duration: float


RequestPin = Callable[[str], Awaitable[str]]


class PairingFailed(Exception):
    pass


class CredentialsRejected(Exception):
    pass


class DeviceRequestFailed(Exception):
    pass


@contextmanager
def device_request(
    device: Device,
    action: str,
    *,
    timeouts: tuple[type[BaseException], ...],
    failures: tuple[type[BaseException], ...],
) -> Iterator[None]:
    try:
        yield
    except timeouts as e:
        raise TimeoutError(f"{device.name} didn't answer {action}: {e}") from e
    except failures as e:
        raise DeviceRequestFailed(f"{device.name} didn't {action}: {e}") from e


class CastSession(ABC):
    def __init__(self, device: Device) -> None:
        self.device = device

    @abstractmethod
    async def play(self, media: Media) -> None: ...

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

    @abstractmethod
    async def close(self) -> None: ...


OpenSession = Callable[[Device, RequestPin], Awaitable[CastSession]]
