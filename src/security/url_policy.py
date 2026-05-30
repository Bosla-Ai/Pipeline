import urllib.parse
import ipaddress
import re

ALLOWED_DOMAINS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "udemy.com",
    "www.udemy.com",
    "coursera.org",
    "www.coursera.org",
}


def is_valid_url(url: str) -> bool:
    """
    Validate if a URL is safe and belongs to the whitelisted learning domains.
    Rejects:
    - Empty/whitespace URLs
    - Non http/https schemes (e.g. javascript:, data:, file:)
    - Localhost, loopback, private IP ranges (SSRFs)
    - Non-whitelisted domains
    - Malformed URLs
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    if not url:
        return False

    try:
        parsed = urllib.parse.urlparse(url)
        # 1. Scheme check
        if parsed.scheme not in ("http", "https"):
            return False

        # 2. Hostname check
        hostname = parsed.hostname
        if not hostname:
            return False
        hostname = hostname.lower()

        # 3. Check if hostname is an IP (to reject private/local IPs)
        # Check if it looks like an IP (IPv4 or IPv6)
        is_ip = False
        try:
            ip = ipaddress.ip_address(hostname)
            is_ip = True
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_unspecified
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_link_local
            ):
                return False
        except ValueError:
            pass

        if is_ip:
            # Learning platforms do not serve directly on raw IPs in search results
            return False

        # 4. Check localhost
        if hostname == "localhost":
            return False

        # 5. Domain whitelist check
        is_whitelisted = hostname in ALLOWED_DOMAINS or hostname.endswith(
            (".youtube.com", ".udemy.com", ".coursera.org")
        )
        if not is_whitelisted:
            return False

        return True
    except Exception:
        return False
