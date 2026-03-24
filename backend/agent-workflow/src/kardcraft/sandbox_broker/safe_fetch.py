"""Safe fetch helper with SSRF guardrails."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse

import httpx
import socket

from .errors import BrokerException

try:
    import dns.asyncresolver  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    dns = None


def _deny(reason: str, detail: str) -> BrokerException:
    return BrokerException(reason, detail)


def _is_forbidden_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or str(addr) == "169.254.169.254"
    )


@dataclass(frozen=True)
class SafeFetchPolicy:
    allow_hosts: tuple[str, ...]
    max_redirects: int = 3
    timeout_seconds: float = 8.0
    max_bytes: int = 1024 * 1024
    allow_headers: tuple[str, ...] = ("accept", "user-agent")
    allowed_ports: tuple[int, ...] = (443,)


def _host_allowed(host: str, allowlist: Iterable[str]) -> bool:
    for candidate in allowlist:
        normalized = candidate.strip().lower()
        if not normalized:
            continue
        if normalized.startswith("."):
            suffix = normalized
            if host.endswith(suffix) and host != suffix[1:]:
                return True
        elif host == normalized:
            return True
    return False


async def _resolve_ips(host: str) -> list[str]:
    ips: list[str] = []
    if dns is not None:
        resolver = dns.asyncresolver.Resolver()
        for record_type in ("A", "AAAA"):
            try:
                answers = await resolver.resolve(host, record_type)
                ips.extend([answer.to_text() for answer in answers])
            except Exception:
                continue
        return ips

    # Fallback when dnspython is unavailable.
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            infos = socket.getaddrinfo(host, None, family, socket.SOCK_STREAM)
            for info in infos:
                ip = info[4][0]
                if ip not in ips:
                    ips.append(ip)
        except Exception:
            continue
    return ips


async def safe_fetch(
    url: str,
    *,
    policy: SafeFetchPolicy,
    headers: Optional[dict[str, str]] = None,
) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise _deny("SAFE_FETCH_SCHEME_DENIED", f"scheme denied: {parsed.scheme}")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise _deny("SAFE_FETCH_HOST_DENIED", "missing host")
    if not _host_allowed(host, policy.allow_hosts):
        raise _deny("SAFE_FETCH_HOST_DENIED", f"host not allowed: {host}")
    port = parsed.port or 443
    if port not in policy.allowed_ports:
        raise _deny("SAFE_FETCH_PORT_DENIED", f"port not allowed: {port}")

    ips = await _resolve_ips(host)
    if not ips:
        raise _deny("SAFE_FETCH_DNS_DENIED", f"dns unresolved: {host}")
    for ip in ips:
        if _is_forbidden_ip(ip):
            raise _deny("SAFE_FETCH_IP_PRIVATE_DENIED", f"forbidden ip: {ip}")

    outgoing_headers = {}
    for k, v in (headers or {}).items():
        if k.lower() in policy.allow_headers:
            outgoing_headers[k] = v

    timeout = httpx.Timeout(policy.timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        current = url
        for _ in range(policy.max_redirects + 1):
            resp = await client.get(current, headers=outgoing_headers)
            if 300 <= resp.status_code < 400:
                location = resp.headers.get("Location", "")
                if not location:
                    raise _deny("SAFE_FETCH_REDIRECT_DENIED", "missing redirect location")
                parsed_redirect = urlparse(location)
                if parsed_redirect.scheme.lower() != "https":
                    raise _deny(
                        "SAFE_FETCH_REDIRECT_DENIED",
                        f"redirect scheme denied: {parsed_redirect.scheme}",
                    )
                host_redirect = (parsed_redirect.hostname or "").strip().lower()
                if not _host_allowed(host_redirect, policy.allow_hosts):
                    raise _deny(
                        "SAFE_FETCH_REDIRECT_DENIED",
                        f"redirect host denied: {host_redirect}",
                    )
                port_redirect = parsed_redirect.port or 443
                if port_redirect not in policy.allowed_ports:
                    raise _deny(
                        "SAFE_FETCH_REDIRECT_DENIED",
                        f"redirect port denied: {port_redirect}",
                    )
                redirect_ips = await _resolve_ips(host_redirect)
                if not redirect_ips:
                    raise _deny(
                        "SAFE_FETCH_REDIRECT_DENIED",
                        f"redirect dns unresolved: {host_redirect}",
                    )
                for ip in redirect_ips:
                    if _is_forbidden_ip(ip):
                        raise _deny(
                            "SAFE_FETCH_REDIRECT_DENIED",
                            f"redirect forbidden ip: {ip}",
                        )
                current = location
                continue

            content = resp.text
            if len(content.encode("utf-8")) > policy.max_bytes:
                raise _deny("SAFE_FETCH_CONTENT_TOO_LARGE", "response too large")
            return content

    raise _deny("SAFE_FETCH_REDIRECT_DENIED", "too many redirects")
