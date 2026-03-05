"""Device list widget for discovered cast targets."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from video_caster.discovery.device import Device


class DeviceSelected(Message):
    """Posted when a device is selected."""
    def __init__(self, device: Device) -> None:
        self.device = device
        super().__init__()


class DeviceList(Widget):
    """Displays discovered cast devices."""

    devices: reactive[list[Device]] = reactive(list, recompose=True)

    def compose(self) -> ComposeResult:
        yield Label("Devices", id="devices-header")
        if not self.devices:
            yield Label("No devices found. Press [bold]d[/bold] to scan.", id="no-devices")
        else:
            yield ListView(
                *[ListItem(Label(device.display_name), name=device.id) for device in self.devices],
                id="device-listview",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_name = event.item.name
        if item_name:
            for device in self.devices:
                if device.id == item_name:
                    self.post_message(DeviceSelected(device))
                    break

    def set_devices(self, devices: list[Device]) -> None:
        self.devices = list(devices)
