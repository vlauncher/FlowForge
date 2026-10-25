"""DNS-rebinding-safe SSRF egress validator with IP pinning and TLS SNI preservation."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import get_settings
from app.core.errors import EgressBlockedError

logger = logging.getLogger("flowforge.egress")

# All 15 blocked network ranges per spec/00-global.md §10
BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),
]

ALLOWED_PORTS = {443, 8443}


def parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a hostname that may be an IPv4, IPv6, decimal, or hex integer literal."""
    # Strip brackets for IPv6 literals e.g. [::1]
    cleaned = host.strip("[]")
    try:
        return ipaddress.ip_address(cleaned)
    except ValueError:
        pass

    # Try decimal or hex integer notation e.g. 2130706433 or 0x7f000001
    try:
        val = int(cleaned, 0)
        if 0 <= val <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(val)
    except ValueError:
        pass

    return None


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address falls within any blocked network or has private flags."""
    # Check IPv4-mapped IPv6 addresses (e.g. ::ffff:169.254.169.254)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        mapped_v4 = ip.ipv4_mapped
        if is_ip_blocked(mapped_v4):
            return True

    # Check against the 15 blocked CIDR ranges
    for net in BLOCKED_NETWORKS:
        if ip in net:
            return True

    # Check standard library properties
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True

    return False


ResolverType = Callable[[str, int], Awaitable[list[ipaddress.IPv4Address | ipaddress.IPv6Address]]]


async def default_resolver(
    hostname: str, port: int
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve hostname using the default asyncio event loop getaddrinfo."""
    loop = asyncio.get_running_loop()
    try:
        addrinfo = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise EgressBlockedError(f"DNS resolution failed for '{hostname}': {e}") from e

    results: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _af, _socktype, _proto, _canonname, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        try:
            results.append(ipaddress.ip_address(ip_str))
        except ValueError:
            continue

    if not results:
        raise EgressBlockedError(f"No IP addresses resolved for '{hostname}'")
    return results


async def validate_and_pin_url(
    url: str,
    allowed_hosts: list[str] | set[str] | None = None,
    *,
    resolver: ResolverType | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Validate URL against SSRF policy and return (pinned_url, host_header, extensions).

    Sequence:
    1. Parse with urllib.parse.urlsplit. Require scheme == 'https', username is None,
       password is None, port in (None, 443, 8443), and hostname in allowed_hosts.
    2. Reject IP literals directly when settings.egress_block_private is True.
    3. Resolve hostname via resolver.
    4. Verify EVERY resolved IP is not blocked.
    5. Pin the first validated IP for connection with TLS sni_hostname and Host header.
    """
    settings = get_settings()

    parsed = urllib.parse.urlsplit(url)

    # 1. Scheme check
    if parsed.scheme.lower() != "https":
        raise EgressBlockedError(
            f"EGRESS_BLOCKED: Only HTTPS scheme allowed, got '{parsed.scheme}'"
        )

    # Userinfo check
    if parsed.username or parsed.password:
        raise EgressBlockedError("EGRESS_BLOCKED: Embedded credentials in URL are forbidden")

    # Port check
    port = parsed.port
    effective_port = port if port is not None else 443
    if effective_port not in ALLOWED_PORTS:
        ports_str = sorted(ALLOWED_PORTS)
        raise EgressBlockedError(
            f"EGRESS_BLOCKED: Port {effective_port} is not allowed (allowed: {ports_str})"
        )

    # Hostname check
    hostname = parsed.hostname
    if not hostname:
        raise EgressBlockedError("EGRESS_BLOCKED: Missing hostname in URL")

    # Allowlist check (if allowed_hosts provided)
    if allowed_hosts is not None and hostname not in allowed_hosts:
        raise EgressBlockedError(f"EGRESS_BLOCKED: Host '{hostname}' is not in allowed hosts")

    # 2. IP literal check
    ip_literal = parse_ip_literal(hostname)
    if ip_literal is not None:
        if settings.egress_block_private and is_ip_blocked(ip_literal):
            raise EgressBlockedError(f"EGRESS_BLOCKED: IP literal {ip_literal} is in blocked range")
        resolved_ips = [ip_literal]
    else:
        # 3. DNS resolution
        dns_func = resolver or default_resolver
        resolved_ips = await dns_func(hostname, effective_port)

    # 4. Check every resolved IP address
    if settings.egress_block_private:
        for resolved_ip in resolved_ips:
            if is_ip_blocked(resolved_ip):
                raise EgressBlockedError(
                    f"EGRESS_BLOCKED: Resolved IP {resolved_ip} is in blocked range"
                )

    # 5. Pin the first validated IP
    pinned_ip = resolved_ips[0]
    pinned_ip_str = str(pinned_ip)
    # IPv6 netloc formatting
    if isinstance(pinned_ip, ipaddress.IPv6Address) or ":" in pinned_ip_str:
        pinned_netloc = f"[{pinned_ip_str}]:{effective_port}"
    else:
        pinned_netloc = f"{pinned_ip_str}:{effective_port}"

    pinned_url = urllib.parse.urlunsplit(
        ("https", pinned_netloc, parsed.path or "/", parsed.query, parsed.fragment)
    )

    extensions = {"sni_hostname": hostname}
    return pinned_url, hostname, extensions
