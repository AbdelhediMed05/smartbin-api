import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from fastapi import Request


@dataclass(frozen=True)
class LimitWindow:
    max_requests: int
    window_seconds: int


class AppRateLimitExceeded(Exception):
    def __init__(self, *, detail: str, retry_after_seconds: int):
        super().__init__(detail)
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()

GLOBAL_IP_LIMIT = LimitWindow(max_requests=120, window_seconds=60)

ROUTE_LIMITS = {
    "auth_register": {
        "ip": LimitWindow(max_requests=3, window_seconds=60),
        "actor": LimitWindow(max_requests=5, window_seconds=15 * 60),
    },
    "auth_login": {
        "ip": LimitWindow(max_requests=5, window_seconds=60),
        "actor": LimitWindow(max_requests=8, window_seconds=10 * 60),
    },
    "auth_refresh": {
        "ip": LimitWindow(max_requests=10, window_seconds=60),
        "actor": LimitWindow(max_requests=20, window_seconds=15 * 60),
    },
    "auth_logout": {
        "ip": LimitWindow(max_requests=30, window_seconds=5 * 60),
        "actor": LimitWindow(max_requests=30, window_seconds=5 * 60),
    },
    "predict": {
        "ip": LimitWindow(max_requests=10, window_seconds=60),
        "actor": LimitWindow(max_requests=20, window_seconds=10 * 60),
    },
    "predict_cancel": {
        "ip": LimitWindow(max_requests=30, window_seconds=5 * 60),
        "actor": LimitWindow(max_requests=30, window_seconds=5 * 60),
    },
    "feedback": {
        "ip": LimitWindow(max_requests=20, window_seconds=60),
        "actor": LimitWindow(max_requests=30, window_seconds=10 * 60),
    },
    "stats_me": {
        "ip": LimitWindow(max_requests=60, window_seconds=60),
        "actor": LimitWindow(max_requests=120, window_seconds=60),
    },
    "leaderboard": {
        "ip": LimitWindow(max_requests=60, window_seconds=60),
        "actor": None,
    },
    "frontend_monitoring": {
        "ip": LimitWindow(max_requests=30, window_seconds=60),
        "actor": None,
    },
}


def enforce_global_ip_limit(request: Request):
    client_ip = _get_client_ip(request)
    retry_after = _register_hit(f"global:{client_ip}", GLOBAL_IP_LIMIT)
    if retry_after is not None:
        raise AppRateLimitExceeded(
            detail="Too many requests from this IP. Please slow down and try again shortly.",
            retry_after_seconds=retry_after,
        )


def enforce_route_limits(
    request: Request,
    *,
    scope: str,
    actor_id: Optional[str] = None,
    actor_hint: Optional[str] = None,
):
    route_policy = ROUTE_LIMITS[scope]
    client_ip = _get_client_ip(request)

    ip_retry_after = _register_hit(f"{scope}:ip:{client_ip}", route_policy["ip"])
    if ip_retry_after is not None:
        raise AppRateLimitExceeded(
            detail="Too many requests from this IP for this endpoint. Please retry later.",
            retry_after_seconds=ip_retry_after,
        )

    actor_key = actor_id or _normalize_actor_hint(actor_hint)
    actor_policy = route_policy.get("actor")
    if actor_key and actor_policy:
        actor_retry_after = _register_hit(f"{scope}:actor:{actor_key}", actor_policy)
        if actor_retry_after is not None:
            raise AppRateLimitExceeded(
                detail="Too many requests for this account. Please retry later.",
                retry_after_seconds=actor_retry_after,
            )


def _register_hit(key: str, window: LimitWindow) -> Optional[int]:
    now = time.time()
    with _lock:
        hits = _hits[key]
        cutoff = now - window.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= window.max_requests:
            retry_after = max(1, int(hits[0] + window.window_seconds - now))
            return retry_after

        hits.append(now)
        return None


def _normalize_actor_hint(actor_hint: Optional[str]) -> Optional[str]:
    if not actor_hint:
        return None
    cleaned = actor_hint.strip().lower()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def _get_client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
