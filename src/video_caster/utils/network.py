import socket
import subprocess


def get_local_ip() -> str:
    """Get the local LAN IP address by connecting to a public DNS server."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]


def get_lan_ip() -> str:
    """Get the local LAN IP, preferring the IP on physical interfaces (en0/en1)
    over VPN/tunnel interfaces. Falls back to get_local_ip()."""
    try:
        # On macOS, ifconfig on en0 (Wi-Fi) or en1 (Ethernet) gives the real LAN IP
        for iface in ("en0", "en1", "en2"):
            try:
                out = subprocess.check_output(
                    ["ipconfig", "getifaddr", iface],
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                ).decode().strip()
                if out and not out.startswith("127."):
                    return out
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
    except Exception:
        pass
    return get_local_ip()


def get_local_ip_for(target_ip: str) -> str:
    """Get the local IP on the same interface that can reach target_ip."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((target_ip, 80))
        return s.getsockname()[0]
