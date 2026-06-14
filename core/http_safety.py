"""SSRF guard for fetching attacker-influenced URLs (event image feeds)."""
import ipaddress
import socket
from urllib.parse import urlparse


def is_public_http_url(url: str) -> bool:
    """True only for http(s) URLs whose host resolves exclusively to globally
    routable IPs (no loopback / private / link-local / reserved ranges)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
        if not infos:
            return False
        return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)
    except Exception:
        return False
