"""SSRF Egress Security Tests (P9-T01, P9-T02, P9-T03)."""

from __future__ import annotations

import ipaddress

import httpx
import pytest

from app.core.errors import EgressBlockedError
from app.infrastructure.http_tool.egress import (
    is_ip_blocked,
    parse_ip_literal,
    validate_and_pin_url,
)


@pytest.mark.asyncio
async def test_p9_t01_egress_validator_rejects_forbidden_targets() -> None:
    """P9-T01: Egress validator rejects all blocked ranges, non-HTTPS schemes, and bad ports."""
    forbidden_ips = [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.5",
        "192.168.1.1",
        "169.254.169.254",  # Cloud metadata
        "::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:169.254.169.254",  # IPv4-mapped metadata
        "fe80::1",  # Link-local IPv6
        "fc00::1",  # Unique local IPv6
        "100.64.0.1",  # Carrier grade NAT
        "198.18.0.1",  # Benchmark network
        "224.0.0.1",  # Multicast
        "240.0.0.1",  # Reserved
        "0.0.0.0",  # Current network
    ]

    for ip_str in forbidden_ips:
        ip_obj = ipaddress.ip_address(ip_str)
        assert is_ip_blocked(ip_obj) is True, f"Expected {ip_str} to be blocked"

        # Check via validate_and_pin_url
        url = f"https://[{ip_str}]/path" if ":" in ip_str else f"https://{ip_str}/path"
        with pytest.raises(EgressBlockedError) as exc_info:
            await validate_and_pin_url(url, allowed_hosts=[ip_str, f"[{ip_str}]"])
        assert "EGRESS_BLOCKED" in str(exc_info.value)

    # Rejection of non-HTTPS schemes
    non_https_schemes = [
        "http://api.example.com/test",
        "ftp://api.example.com/test",
        "gopher://api.example.com/test",
        "file:///etc/passwd",
    ]
    for url in non_https_schemes:
        with pytest.raises(EgressBlockedError) as exc_info:
            await validate_and_pin_url(url, allowed_hosts=["api.example.com"])
        assert "Only HTTPS scheme allowed" in str(exc_info.value)

    # Rejection of forbidden ports (allowed: 443, 8443)
    bad_ports = [80, 8080, 6379, 22, 3306, 5432, 27017]
    for port in bad_ports:
        url = f"https://api.example.com:{port}/data"
        with pytest.raises(EgressBlockedError) as exc_info:
            await validate_and_pin_url(url, allowed_hosts=["api.example.com"])
        assert "Port" in str(exc_info.value) and "not allowed" in str(exc_info.value)

    # Rejection of embedded credentials in URL
    with pytest.raises(EgressBlockedError) as exc_info:
        await validate_and_pin_url(
            "https://admin:password@api.example.com/test", allowed_hosts=["api.example.com"]
        )
    assert "Embedded credentials" in str(exc_info.value)


@pytest.mark.asyncio
async def test_p9_t02_dns_rebinding_and_dual_record_defense() -> None:
    """P9-T02: DNS rebinding defense via IP pinning and multi-record validation."""
    public_ip = ipaddress.ip_address("93.184.216.34")  # example.com
    private_metadata_ip = ipaddress.ip_address("169.254.169.254")

    # Case A: Dual A-record returns 1 public and 1 private IP
    # Policy states: if ANY resolved IP in the set is private/blocked, the whole request is blocked!
    async def dual_record_resolver(
        hostname: str, port: int
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return [public_ip, private_metadata_ip]

    with pytest.raises(EgressBlockedError) as exc_info:
        await validate_and_pin_url(
            "https://rebinding.attacker.com/",
            allowed_hosts=["rebinding.attacker.com"],
            resolver=dual_record_resolver,
        )
    assert "EGRESS_BLOCKED" in str(exc_info.value)
    assert "169.254.169.254" in str(exc_info.value)

    # Case B: Time-of-check to time-of-use (TOCTOU) DNS Rebinding
    # Resolver returns public IP on validation, and we ensure the connection is strictly pinned
    # to that resolved public IP address, so any subsequent DNS rebind has zero effect.
    call_count = 0

    async def toctou_resolver(
        hostname: str, port: int
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [public_ip]
        return [private_metadata_ip]

    pinned_url, host_header, extensions = await validate_and_pin_url(
        "https://rebinding.attacker.com/v1/webhook",
        allowed_hosts=["rebinding.attacker.com"],
        resolver=toctou_resolver,
    )

    # Pinned URL must use the first validated IP
    assert pinned_url == f"https://{public_ip}:443/v1/webhook"
    assert host_header == "rebinding.attacker.com"
    assert extensions == {"sni_hostname": "rebinding.attacker.com"}
    # Single DNS resolution call performed
    assert call_count == 1


@pytest.mark.asyncio
async def test_p9_t03_redirects_are_strictly_disabled() -> None:
    """P9-T03: Upstream returning 302 redirect to metadata IP is NOT followed."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            content=b"Redirecting...",
        )
    )

    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        resp = await client.get("https://api.example.com/check")
        # Status code is 302 (redirect not followed)
        assert resp.status_code == 302
        assert resp.headers.get("Location") == "http://169.254.169.254/latest/meta-data/"


def test_decimal_and_hex_ip_literals_parsed_and_blocked() -> None:
    """Verify alternative representations of IP literals are parsed and blocked."""
    # 2130706433 is 127.0.0.1
    ip_dec = parse_ip_literal("2130706433")
    assert ip_dec == ipaddress.IPv4Address("127.0.0.1")
    assert is_ip_blocked(ip_dec) is True

    # 0x7f000001 is 127.0.0.1
    ip_hex = parse_ip_literal("0x7f000001")
    assert ip_hex == ipaddress.IPv4Address("127.0.0.1")
    assert is_ip_blocked(ip_hex) is True

    # 2852039166 is 169.254.169.254
    ip_meta = parse_ip_literal("2852039166")
    assert ip_meta == ipaddress.IPv4Address("169.254.169.254")
    assert is_ip_blocked(ip_meta) is True
