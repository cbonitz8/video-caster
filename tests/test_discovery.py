from __future__ import annotations

from video_caster.discovery.device import Device, DeviceType
from video_caster.discovery.scanner import scan_all, udn_from_usn

HOST_IP = "192.168.10.66"

TV = Device(id="cc-uuid", name="Living Room", device_type=DeviceType.CHROMECAST,
            address="192.168.10.17", port=8009)
THIS_MAC = Device(id="mac-id", name="Caleb’s MacBook Pro", device_type=DeviceType.APPLETV,
                  address=HOST_IP)
APPLE_TV = Device(id="atv-id", name="Den", device_type=DeviceType.APPLETV,
                  address="192.168.10.30")
SAMSUNG_AIRPLAY = Device(id="samsung-atv-id", name="Samsung", device_type=DeviceType.APPLETV,
                         address="192.168.10.40")
SAMSUNG_DLNA = Device(id="uuid:samsung", name="Samsung", device_type=DeviceType.DLNA,
                      address="192.168.10.40", port=9197,
                      location="http://192.168.10.40:9197/dmr")


def scanners(chromecasts=(), apple_tvs=(), dlna=(), probe_hits=None):
    probed: list[str] = []

    def found(devices):
        async def scan(timeout):
            return list(devices)
        return scan

    async def probe(ip):
        probed.append(ip)
        return (probe_hits or {}).get(ip)

    return probed, {
        "chromecasts": found(chromecasts),
        "apple_tvs": found(apple_tvs),
        "dlna": found(dlna),
        "probe_dlna": probe,
        "local_ips": lambda: {"127.0.0.1", HOST_IP},
    }


async def test_scan_leaves_out_the_host_itself():
    probed, kw = scanners(chromecasts=[TV], apple_tvs=[THIS_MAC, APPLE_TV])

    devices = await scan_all(1.0, **kw)

    assert [d.id for d in devices] == ["cc-uuid", "atv-id"]
    assert HOST_IP not in probed


async def test_scan_prefers_dlna_over_airplay_on_the_same_ip():
    _, kw = scanners(apple_tvs=[SAMSUNG_AIRPLAY], probe_hits={"192.168.10.40": SAMSUNG_DLNA})

    devices = await scan_all(1.0, **kw)

    assert devices == [SAMSUNG_DLNA]


def test_dlna_id_is_the_udn_not_the_address():
    usn = "uuid:4d696e69-444c-164e-9d41-b827eb54e2ef::urn:schemas-upnp-org:device:MediaRenderer:1"
    assert udn_from_usn(usn) == "uuid:4d696e69-444c-164e-9d41-b827eb54e2ef"
