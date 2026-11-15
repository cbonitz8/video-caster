"""Unified device discovery for Chromecast, Apple TV, and DLNA."""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable
from urllib.parse import urlparse

import aiohttp
import pychromecast
import pyatv
from async_upnp_client.search import async_search

from video_caster.discovery.device import Device, DeviceType
from video_caster.utils.network import host_addresses

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="discovery")

Scan = Callable[[float], Awaitable[list[Device]]]


async def scan_chromecasts(timeout: float = 5.0) -> list[Device]:
    loop = asyncio.get_running_loop()

    def _scan() -> list[Device]:
        chromecasts, browser = pychromecast.get_chromecasts(timeout=timeout)
        browser.stop_discovery()
        return [
            Device(
                id=str(cc.cast_info.uuid),
                name=cc.cast_info.friendly_name,
                device_type=DeviceType.CHROMECAST,
                address=str(cc.cast_info.host),
                port=cc.cast_info.port,
                model=cc.cast_info.model_name or "",
            )
            for cc in chromecasts
        ]

    try:
        return await loop.run_in_executor(_executor, _scan)
    except Exception as e:
        log.error("Chromecast discovery failed: %s", e)
        return []


async def scan_apple_tvs(timeout: float = 5.0) -> list[Device]:
    devices = []
    try:
        atvs = await pyatv.scan(asyncio.get_running_loop(), timeout=timeout)
    except Exception as e:
        log.error("Apple TV discovery failed: %s", e)
        return []
    for atv in atvs:
        if atv.identifier is None:
            log.warning("Skipping Apple TV %s (%s): no identifier", atv.name, atv.address)
            continue
        devices.append(Device(
            id=atv.identifier,
            name=atv.name,
            device_type=DeviceType.APPLETV,
            address=str(atv.address),
            model=atv.device_info.model.name if atv.device_info else "",
        ))
    return devices


def udn_from_usn(usn: str) -> str:
    return usn.split("::")[0]


async def _fetch_dlna_description(location: str) -> tuple[str, str, str, bool]:
    """Returns (friendly_name, model, udn, is_media_renderer)."""
    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(location, timeout=aiohttp.ClientTimeout(total=1.5)) as resp:
                if resp.status != 200:
                    return "", "", "", False
                text = await resp.text()
        root = ET.fromstring(text)
        device_el = root.find("d:device", ns)
        if device_el is not None:
            name = device_el.findtext("d:friendlyName", "", ns)
            model = device_el.findtext("d:modelName", "", ns)
            udn = device_el.findtext("d:UDN", "", ns)
            is_renderer = "MediaRenderer" in device_el.findtext("d:deviceType", "", ns)
            return name, model, udn, is_renderer
    except Exception:
        pass
    return "", "", "", False


_DLNA_PROBE_PATHS = [
    "/dmr",                   # Samsung
    "/dmr/SamsungMRDesc.xml", # Samsung (alt)
    "/xml/device_description.xml",  # LG
    "/DeviceDescription.xml", # Sony
    "/description.xml",       # generic
]


async def scan_dlna(timeout: float = 5.0) -> list[Device]:
    locations: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()
    target = "urn:schemas-upnp-org:device:MediaRenderer:1"

    async def _on_response(response):
        location = response.get("location", "")
        usn = response.get("usn", "")
        if not location or not usn or usn in seen:
            return
        seen.add(usn)
        parsed = urlparse(location)
        locations.append((location, parsed.hostname or "", usn, parsed.port or 0))

    try:
        log.info("Starting DLNA discovery (target=%s, timeout=%s)", target, timeout)
        await async_search(_on_response, timeout=int(timeout), search_target=target)
        log.info("DLNA discovery found %d raw responses", len(locations))
    except Exception as e:
        log.error("DLNA discovery failed: %s", e, exc_info=True)

    names = await asyncio.gather(
        *[_fetch_dlna_description(loc) for loc, _, _, _ in locations],
        return_exceptions=True,
    )

    devices: list[Device] = []
    for (location, address, usn, port), name_result in zip(locations, names):
        if isinstance(name_result, Exception):
            friendly_name, model = "", ""
        else:
            friendly_name, model, _, _ = name_result
        udn = udn_from_usn(usn)
        devices.append(Device(
            id=udn,
            name=friendly_name or udn.replace("uuid:", ""),
            device_type=DeviceType.DLNA,
            address=address,
            port=port,
            model=model,
            location=location,
        ))
    return devices


async def probe_dlna_on_ip(ip: str) -> Device | None:
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
        name, model, udn, is_renderer = result
        if not is_renderer:
            continue
        if not udn:
            log.warning("DLNA probe hit %s has no UDN; skipping", url)
            continue
        log.info("DLNA probe hit: %s → %s (%s)", url, name, model)
        return Device(
            id=udn,
            name=name or ip,
            device_type=DeviceType.DLNA,
            address=ip,
            port=port,
            model=model,
            location=url,
        )
    return None


async def scan_all(
    timeout: float = 5.0,
    *,
    chromecasts: Scan = scan_chromecasts,
    apple_tvs: Scan = scan_apple_tvs,
    dlna: Scan = scan_dlna,
    probe_dlna: Callable[[str], Awaitable[Device | None]] = probe_dlna_on_ip,
    local_ips: Callable[[], set[str]] = host_addresses,
) -> list[Device]:
    """Run Chromecast, Apple TV, and DLNA discovery concurrently."""
    results = await asyncio.gather(
        chromecasts(timeout), apple_tvs(timeout), dlna(timeout), return_exceptions=True,
    )

    def _safe(result) -> list[Device]:
        if isinstance(result, Exception):
            log.error("Discovery error: %s", result)
            return []
        return result

    host = local_ips()
    cc_devices, atv_devices, dlna_devices = (
        [d for d in _safe(r) if d.address not in host] for r in results
    )

    log.info("Discovery raw counts: chromecast=%d, appletv=%d, dlna=%d",
             len(cc_devices), len(atv_devices), len(dlna_devices))

    # Many smart TVs (Samsung, LG) advertise AirPlay via mDNS but only work via
    # DLNA, and SSDP multicast is often blocked, so probe AirPlay IPs for DLNA.
    dlna_ips = {d.address for d in dlna_devices}
    probe_ips = [d.address for d in atv_devices if d.address not in dlna_ips]
    if probe_ips:
        log.info("Probing %d AirPlay IPs for DLNA: %s", len(probe_ips), probe_ips)
        probe_results = await asyncio.gather(
            *[probe_dlna(ip) for ip in probe_ips], return_exceptions=True,
        )
        for result in probe_results:
            if isinstance(result, Device):
                dlna_devices.append(result)
                dlna_ips.add(result.address)

    # Real Apple TVs don't advertise DLNA, so an AirPlay entry sharing an IP
    # with a DLNA renderer is a non-Apple TV that won't work via AirPlay.
    for d in atv_devices:
        if d.address in dlna_ips:
            log.info("Removing AirPlay entry for %s (%s) — DLNA preferred", d.name, d.address)
    atv_devices = [d for d in atv_devices if d.address not in dlna_ips]

    devices = cc_devices + atv_devices + dlna_devices
    log.info("Found %d devices total", len(devices))
    return devices
