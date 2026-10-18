"""Resolve client IPs without trusting spoofable forwarding headers."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable

from fastapi import Request

_BRACKETED_IPV6 = re.compile(r"^\[([^\]]+)\](?::\d+)?$")


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = value.strip()
    if not candidate or "%" in candidate:
        return None
    bracketed = _BRACKETED_IPV6.fullmatch(candidate)
    if bracketed:
        candidate = bracketed.group(1)
    elif candidate.count(":") == 1:
        host, port = candidate.rsplit(":", 1)
        if port.isdigit():
            candidate = host
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _is_trusted(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    trusted_networks: Iterable,
) -> bool:
    return any(
        address.version == network.version and address in network
        for network in trusted_networks
    )


def resolve_client_ip(request: Request, trusted_networks: tuple = ()) -> str:
    """Resolve the client address, trusting XFF only behind trusted peers."""
    peer = request.client.host if request.client else "unknown"
    if not trusted_networks or peer == "unknown":
        return peer

    peer_address = _parse_ip(peer)
    if peer_address is None or not _is_trusted(peer_address, trusted_networks):
        return peer

    forwarded_for = request.headers.get("X-Forwarded-For", "")
    for value in reversed(forwarded_for.split(",")):
        address = _parse_ip(value)
        if address is None or _is_trusted(address, trusted_networks):
            continue
        return str(address)
    return peer
