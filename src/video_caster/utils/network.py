import errno
import socket

import ifaddr


def get_local_ip() -> str:
    """Get the local LAN IP address by connecting to a public DNS server."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]


def get_local_ip_for(target_ip: str) -> str:
    """Get the local IP on the same interface that can reach target_ip."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((target_ip, 80))
        return s.getsockname()[0]


def multicast_blocked() -> bool:
    """True if the OS refuses multicast sends from this process.

    macOS returns EHOSTUNREACH for multicast when the responsible app
    (the terminal) lacks Local Network permission, even while its toggle
    in System Settings shows on. Discovery then silently finds nothing.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.sendto(b"\0", ("224.0.0.251", 5353))
        except OSError as e:
            if e.errno == errno.EHOSTUNREACH:
                return True
            raise
    return False


def host_addresses() -> set[str]:
    return {
        ip.ip
        for adapter in ifaddr.get_adapters()
        for ip in adapter.ips
        if isinstance(ip.ip, str)
    }
