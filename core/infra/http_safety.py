"""SSRF guard for fetching attacker-influenced URLs (event image feeds)."""
import contextlib
import ipaddress
import socket
import threading
from urllib.parse import urlparse

import httpx


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


_resolve_lock = threading.Lock()


@contextlib.contextmanager
def _pinned_host(host: str, ip: str):
    """Pin ``host``→``ip`` in ``socket.getaddrinfo`` for the duration of a request so the connection
    can't be DNS-rebound to an internal IP between our public-IP validation and the actual connect
    (the TOCTOU is_public_http_url alone can't close). Every OTHER host passes straight through to the
    real resolver, so concurrent lookups elsewhere in the process are unaffected; a lock serialises
    overlapping pins. Used only on the background media/render fetch paths, never the API hot path."""
    real = socket.getaddrinfo

    def _patched(h, *a, **k):
        return real(ip if h == host else h, *a, **k)

    with _resolve_lock:
        socket.getaddrinfo = _patched
        try:
            yield
        finally:
            socket.getaddrinfo = real


def safe_get(url: str, **kwargs) -> httpx.Response:
    """SSRF-safe httpx GET for an attacker-influenced URL: reject non-public hosts, block redirects,
    and PIN the validated public IP for the connection so a rebind can't swap it for an internal host
    after the check. Raises ValueError when the URL isn't a public http(s) target — the caller treats
    that like any dead/blocked image URL."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme not in ("http", "https") or not host:
        raise ValueError("non-http url")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ValueError("dns resolution failed") from exc
    ips = [info[4][0] for info in infos]
    if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("host is not public")
    kwargs.setdefault("follow_redirects", False)
    with _pinned_host(host, ips[0]):
        return httpx.get(url, **kwargs)
