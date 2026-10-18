import asyncio
import ipaddress
import json

import pytest
from fastapi import Request, Response
from pydantic import ValidationError

from backend.api.client_identity import resolve_client_ip
from backend.api.middleware import RateLimitMiddleware, StructuredLoggingMiddleware
from backend.api.readiness import _probe_allowed
from backend.core.config import AppSettings


def make_request(peer: str | None, forwarded_for: str = "") -> Request:
    headers = []
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "headers": headers,
        "client": (peer, 12345) if peer is not None else None,
        "server": ("testserver", 80),
    })


def networks(value: str):
    return AppSettings(_env_file=None, trusted_proxies=value).trusted_proxy_networks


def test_trusted_proxy_configuration_normalizes_and_parses():
    settings = AppSettings(
        _env_file=None,
        trusted_proxies=" 192.0.2.10 , , 2001:db8::/64 ",
    )
    assert settings.trusted_proxies == "192.0.2.10/32,2001:db8::/64"
    assert settings.trusted_proxy_networks == (
        ipaddress.ip_network("192.0.2.10/32"),
        ipaddress.ip_network("2001:db8::/64"),
    )


@pytest.mark.parametrize("value", ["not-an-ip", "192.0.2.0/33", "0.0.0.0/0", "::/0"])
def test_trusted_proxy_configuration_rejects_invalid_or_catch_all(value):
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, trusted_proxies=value)


def test_empty_trusted_proxy_configuration_is_legal():
    settings = AppSettings(_env_file=None, trusted_proxies=" , ")
    assert settings.trusted_proxies == ""
    assert settings.trusted_proxy_networks == ()


@pytest.mark.parametrize("value", ["192.0.2.10", "2001:db8::10", "192.0.2.0/24", "2001:db8::/64"])
def test_trusted_proxy_configuration_accepts_ip_and_cidr(value):
    assert len(AppSettings(_env_file=None, trusted_proxies=value).trusted_proxy_networks) == 1


def test_default_configuration_ignores_forwarded_for():
    request = make_request("192.0.2.10", "198.51.100.20")
    assert resolve_client_ip(request) == "192.0.2.10"


def test_trusted_proxy_uses_rightmost_non_trusted_address():
    trusted = networks("192.0.2.10,192.0.2.0/24,2001:db8::/64")
    request = make_request(
        "192.0.2.10",
        "203.0.113.9, 192.0.2.20, 2001:db8::1, [198.51.100.20]:443",
    )
    assert resolve_client_ip(request, trusted) == "198.51.100.20"


def test_leftmost_forwarded_value_cannot_override_rightmost_real_client():
    trusted = networks("192.0.2.0/24")
    request = make_request("192.0.2.10", "198.51.100.99, 203.0.113.8, 192.0.2.20")
    assert resolve_client_ip(request, trusted) == "203.0.113.8"


def test_untrusted_peer_ignores_forwarded_for_even_with_trusted_values():
    trusted = networks("192.0.2.0/24")
    request = make_request("198.51.100.10", "203.0.113.9, 192.0.2.20")
    assert resolve_client_ip(request, trusted) == "198.51.100.10"


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected", "trusted"),
    [
        ("192.0.2.10", "203.0.113.8, 192.0.2.11", "203.0.113.8", "192.0.2.0/24"),
        ("2001:db8::10", "2001:db8:1::8, 2001:db8::11", "2001:db8:1::8", "2001:db8::/64"),
        ("192.0.2.10", "bad-token, 192.0.2.11", "192.0.2.10", "192.0.2.0/24"),
        ("192.0.2.10", "[2001:db8::11]:8443", "2001:db8::11", "192.0.2.0/24"),
        ("192.0.2.10", "203.0.113.11:8443", "203.0.113.11", "192.0.2.0/24"),
        ("192.0.2.10", "bad-token, fe80::1%en0", "192.0.2.10", "192.0.2.0/24"),
    ],
)
def test_forwarded_for_parsing_cases(peer, forwarded, expected, trusted):
    assert resolve_client_ip(make_request(peer, forwarded), networks(trusted)) == expected


def test_client_none_and_ipv4_ipv6_mismatch_are_safe():
    assert resolve_client_ip(make_request(None, "203.0.113.10"), networks("192.0.2.0/24")) == "unknown"
    assert resolve_client_ip(
        make_request("192.0.2.10", "2001:db8::10"), networks("192.0.2.0/24")
    ) == "2001:db8::10"


def test_rate_limit_and_logging_share_resolved_identity(caplog):
    trusted = networks("192.0.2.0/24")
    request = make_request("192.0.2.10", "203.0.113.10")
    limiter = RateLimitMiddleware(app=None, enabled=False, trusted_proxies=trusted)
    logger = StructuredLoggingMiddleware(app=None, trusted_proxies=trusted)
    assert limiter._get_client_id(request) == resolve_client_ip(request, trusted)

    async def call_next(_request):
        return Response("ok")

    with caplog.at_level("INFO"):
        asyncio.run(logger.dispatch(request, call_next))
    start = next(json.loads(record.message) for record in caplog.records if "request_start" in record.message)
    assert start["client"] == "203.0.113.10"


def test_readiness_still_requires_token_behind_trusted_proxy(monkeypatch):
    monkeypatch.setattr("backend.api.readiness.settings.health_probe_token", None)
    request = make_request("192.0.2.10", "203.0.113.10")
    assert _probe_allowed(request) is False
