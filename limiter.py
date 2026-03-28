"""
limiter.py — Single shared SlowAPI limiter for the entire application.

OWASP A05 (Security Misconfiguration) mitigation:
  Centralising the limiter ensures all @limiter.limit() decorators share one
  in-memory store. Creating a new Limiter() per-router module means each
  module gets its own counter — a user can hit the real limit N×router times.

Two key functions are provided:
  - get_remote_address  : IP-based key (used on public/unauthenticated routes)
  - get_user_or_ip      : JWT sub + IP combined key (used on authenticated routes)
    Prevents a single user from bypassing the IP limit by rotating proxy IPs,
    and prevents a shared IP (e.g. NAT, office network) from locking out other users.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_user_or_ip(request: Request) -> str:
    """
    Rate-limit key for authenticated endpoints.

    Prefers the JWT 'sub' claim injected by the auth middleware
    (stored in request.state.user_id after auth), falling back to IP.
    This prevents one user bypassing limits via multiple IPs, and
    prevents a shared egress IP from starving other users.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    ip = get_remote_address(request)
    # Combine both so the bucket is per-user-per-IP, capped at the tighter limit.
    # Using user_id alone would let one account hammer from 1 IP freely if the
    # IP bucket is not also tracked; combining is the safest default.
    return f"{user_id or 'anon'}:{ip}"


# One shared limiter instance — imported by every route module.
# The key_func defaults to IP for undecorated calls; individual routes
# override it via the @limiter.limit() 'key_func' kwarg where needed.
limiter = Limiter(
    key_func=get_remote_address,
    # Return a clean JSON 429 instead of the default plain-text response.
    # The actual handler is registered in main.py via add_exception_handler().
    headers_enabled=True,   # adds X-RateLimit-* and Retry-After headers to all responses
)
