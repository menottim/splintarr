"""
SSRF (Server-Side Request Forgery) Protection for Splintarr.

This module provides URL validation to prevent SSRF attacks when users
configure Sonarr/Radarr instance URLs. Blocks requests to:
- Private IP ranges (RFC 1918)
- Loopback addresses
- Cloud metadata endpoints (AWS, GCP, Azure)
- Link-local addresses
"""

import ipaddress
import socket
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()

# Blocked IP ranges for SSRF protection
BLOCKED_NETWORKS = [
    # IPv4
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("10.0.0.0/8"),  # Private
    ipaddress.ip_network("172.16.0.0/12"),  # Private
    ipaddress.ip_network("192.168.0.0/16"),  # Private
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / AWS metadata
    ipaddress.ip_network("0.0.0.0/8"),  # Current network
    ipaddress.ip_network("100.64.0.0/10"),  # Shared address space (CGN)
    ipaddress.ip_network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("198.18.0.0/15"),  # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("255.255.255.255/32"),  # Broadcast
    # IPv6
    ipaddress.ip_network("::1/128"),  # Loopback
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ipaddress.ip_network("fc00::/7"),  # Private (Unique Local Addresses)
    ipaddress.ip_network("fe80::/10"),  # Link-local
    ipaddress.ip_network("ff00::/8"),  # Multicast
]


class SSRFError(Exception):
    """Exception raised when SSRF protection blocks a URL."""

    pass


def validate_instance_url(url: str, allow_local: bool = False) -> None:
    """
    Validate a Sonarr/Radarr instance URL for SSRF protection.

    Args:
        url: The URL to validate
        allow_local: If True, allow localhost and private IPs (development only)

    Raises:
        SSRFError: If URL is blocked for SSRF protection
        ValueError: If URL format is invalid

    Example:
        >>> validate_instance_url("https://sonarr.example.com")  # OK
        >>> validate_instance_url("http://169.254.169.254")  # Raises SSRFError
        >>> validate_instance_url("http://localhost", allow_local=True)  # OK
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL format: {e}") from e

    # Require HTTP/HTTPS
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")

    # Require hostname
    if not parsed.hostname:
        raise ValueError("URL must have a hostname")

    hostname = parsed.hostname.lower()

    # Check for localhost/loopback hostnames
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        if allow_local:
            logger.warning(
                "allowing_local_instance_url",
                hostname=hostname,
                message="Local instance allowed (development only)",
            )
            return
        raise SSRFError(f"Localhost/loopback addresses are blocked: {hostname}")

    # Resolve hostname to IP address
    try:
        # Get all IP addresses for this hostname (handles multiple A/AAAA records)
        addr_info = socket.getaddrinfo(
            hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            family=socket.AF_UNSPEC,  # Allow both IPv4 and IPv6
            type=socket.SOCK_STREAM,
        )

        # Extract unique IP addresses
        ip_addresses = list(set(addr[4][0] for addr in addr_info))

    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname '{hostname}': {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to resolve hostname '{hostname}': {e}") from e

    # Check each resolved IP against blocked networks
    for ip_str in ip_addresses:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as e:
            raise ValueError(f"Invalid IP address '{ip_str}': {e}") from e

        # Check against blocked networks
        if not allow_local:
            for network in BLOCKED_NETWORKS:
                if ip in network:
                    logger.warning(
                        "ssrf_blocked",
                        url=url,
                        hostname=hostname,
                        ip=str(ip),
                        blocked_network=str(network),
                    )
                    raise SSRFError(
                        f"URL resolves to blocked network: {network}. "
                        f"Private IPs are not allowed for security reasons."
                    )

    # URL passed all checks
    logger.info(
        "instance_url_validated",
        url=url,
        hostname=hostname,
        ips=ip_addresses,
        allow_local=allow_local,
    )


def is_safe_url(url: str, allow_local: bool = False) -> bool:
    """
    Check if a URL is safe (non-blocking wrapper).

    Args:
        url: The URL to check
        allow_local: If True, allow localhost and private IPs

    Returns:
        bool: True if URL is safe, False if blocked

    Example:
        >>> is_safe_url("https://sonarr.example.com")
        True
        >>> is_safe_url("http://169.254.169.254")
        False
    """
    try:
        validate_instance_url(url, allow_local=allow_local)
        return True
    except (SSRFError, ValueError):
        return False
