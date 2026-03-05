"""Unified device discovery for Chromecast, Apple TV, and DLNA."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import pychromecast
import pyatv
from async_upnp_client.search import async_search

from video_caster.discovery.device import Device, DeviceType

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="discovery")


async def scan_chromecasts(timeout: float = 5.0) -> list[Device]:
    """Discover Chromecast devices on the network."""
    loop = asyncio.get_running_loop()
    devices = []

    def _scan():
        chromecasts, browser = pychromecast.get_chromecasts(timeout=timeout)
        result = []
        for cc in chromecasts:
            result.append((
                cc.cast_info.friendly_name,
                str(cc.cast_info.host),
                cc.cast_info.port,
                cc.cast_info.model_name,
                cc,
                browser,
            ))
        return result

    try:
        found = await loop.run_in_executor(_executor, _scan)
        for name, host, port, model, cast, browser in found:
            devices.append(Device(
                name=name,
                device_type=DeviceType.CHROMECAST,
                address=host,
                port=port,
                model=model or "",
                protocol_config={"cast": cast, "browser": browser},
            ))
    except Exception as e:
        log.error("Chromecast discovery failed: %s", e)

    return devices


async def scan_apple_tvs(timeout: float = 5.0) -> list[Device]:
    """Discover Apple TV devices on the network."""
    devices = []
    try:
        atvs = await pyatv.scan(asyncio.get_running_loop(), timeout=timeout)
        for atv in atvs:
            address = str(atv.address)
            devices.append(Device(
                name=atv.name,
                device_type=DeviceType.APPLETV,
                address=address,
                port=0,
                model=atv.device_info.model.name if atv.device_info else "",
                protocol_config={"config": atv},
            ))
    except Exception as e:
        log.error("Apple TV discovery failed: %s", e)

    return devices


async def _fetch_dlna_description(location: str) -> tuple[str, str, bool]:
    """Fetch device description XML from a URL.

    Returns (friendly_name, model, is_media_renderer).
    """
    import xml.etree.ElementTree as ET

    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(location, timeout=aiohttp.ClientTimeout(total=1.5)) as resp:
                if resp.status != 200:
                    return "", "", False
                text = await resp.text()
        root = ET.fromstring(text)
        device_el = root.find("d:device", ns)
        if device_el is not None:
            name = device_el.findtext("d:friendlyName", "", ns)
            model = device_el.findtext("d:modelName", "", ns)
            device_type = device_el.findtext("d:deviceType", "", ns)
            is_renderer = "MediaRenderer" in device_type
            return name, model, is_renderer
    except Exception:
        pass
    return "", "", False


# Common DLNA description paths found on smart TVs
_DLNA_PROBE_PATHS = [
    "/dmr",                   # Samsung
    "/dmr/SamsungMRDesc.xml", # Samsung (alt)
    "/xml/device_description.xml",  # LG
    "/DeviceDescription.xml", # Sony
    "/description.xml",       # generic
]


async def scan_dlna(timeout: float = 5.0) -> list[Device]:
    """Discover DLNA/UPnP MediaRenderer devices on the network."""
    from urllib.parse import urlparse

    locations: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()
    target = "urn:schemas-upnp-org:device:MediaRenderer:1"

    async def _on_response(response):
        location = response.get("location", "")
        usn = response.get("usn", "")
        if not location or usn in seen:
            return
        seen.add(usn)
        parsed = urlparse(location)
        address = parsed.hostname or ""
        port = parsed.port or 0
        locations.append((location, address, usn, port))

    try:
        log.info("Starting DLNA discovery (target=%s, timeout=%s)", target, timeout)
        await async_search(_on_response, timeout=int(timeout), search_target=target)
        log.info("DLNA discovery found %d raw responses", len(locations))
    except Exception as e:
        log.error("DLNA discovery failed: %s", e, exc_info=True)

    # Fetch friendly names in parallel
    devices: list[Device] = []
    name_tasks = [_fetch_dlna_description(loc) for loc, _, _, _ in locations]
    names = await asyncio.gather(*name_tasks, return_exceptions=True)

    for (location, address, usn, port), name_result in zip(locations, names):
        if isinstance(name_result, Exception):
            friendly_name, model = "", ""
        else:
            friendly_name, model, _ = name_result
        if not friendly_name:
            friendly_name = usn.split("::")[0].replace("uuid:", "") if usn else address
        devices.append(Device(
            name=friendly_name,
            device_type=DeviceType.DLNA,
            address=address,
            port=port,
            model=model,
            protocol_config={"location": location},
        ))

    return devices


async def _probe_dlna_on_ip(ip: str) -> Device | None:
    """Try known DLNA description paths on an IP to find a MediaRenderer."""
    urls = [
        (port, f"http://{ip}:{port}{path}")
        for port in (9197, 8080, 52235, 7676)
        for path in _DLNA_PROBE_PATHS
    ]
    results = await asyncio.gather(
        *[_fetch_dlna_description(url) for _, url in urls],
        return_exceptions=True,
    )
    for (port, url), result in zip(urls, results):
        if isinstance(result, Exception):
            continue
        name, model, is_renderer = result
        if is_renderer:
            log.info("DLNA probe hit: %s → %s (%s)", url, name, model)
            return Device(
                name=name or ip,
                device_type=DeviceType.DLNA,
                address=ip,
                port=port,
                model=model,
                protocol_config={"location": url},
            )
    return None


async def scan_all(timeout: float = 5.0) -> list[Device]:
    """Run Chromecast, Apple TV, and DLNA discovery concurrently."""
    cc_result, atv_result, dlna_result = await asyncio.gather(
        scan_chromecasts(timeout),
        scan_apple_tvs(timeout),
        scan_dlna(timeout),
        return_exceptions=True,
    )

    def _safe(result):
        if isinstance(result, list):
            return result
        if isinstance(result, Exception):
            log.error("Discovery error: %s", result)
        return []

    chromecasts = _safe(cc_result)
    apple_tvs = _safe(atv_result)
    dlna_devices = _safe(dlna_result)

    log.info("Discovery raw counts: chromecast=%d, appletv=%d, dlna=%d",
             len(chromecasts), len(apple_tvs), len(dlna_devices))

    # Fallback: for AirPlay-discovered IPs not already found via SSDP,
    # probe known DLNA description URLs. Many smart TVs (Samsung, LG)
    # advertise AirPlay via mDNS but only work via DLNA, and SSDP
    # multicast is often blocked by routers/firewalls.
    dlna_ips = {d.address for d in dlna_devices}
    probe_ips = [d.address for d in apple_tvs if d.address not in dlna_ips]
    if probe_ips:
        log.info("Probing %d AirPlay IPs for DLNA: %s", len(probe_ips), probe_ips)
        probe_results = await asyncio.gather(
            *[_probe_dlna_on_ip(ip) for ip in probe_ips],
            return_exceptions=True,
        )
        for result in probe_results:
            if isinstance(result, Device):
                dlna_devices.append(result)
                dlna_ips.add(result.address)

    # Deduplicate: if the same IP appears as both DLNA and AirPlay, keep
    # only DLNA — real Apple TVs don't advertise DLNA, so the AirPlay
    # entry is a non-Apple TV that won't work via AirPlay.
    removed = [d for d in apple_tvs if d.address in dlna_ips]
    for d in removed:
        log.info("Removing AirPlay entry for %s (%s) — DLNA preferred", d.name, d.address)
    apple_tvs = [d for d in apple_tvs if d.address not in dlna_ips]

    devices = chromecasts + apple_tvs + dlna_devices
    log.info("Found %d devices total", len(devices))
    return devices
