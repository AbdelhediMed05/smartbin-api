from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "pass",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "jwt",
    "dsn",
}

REDACTED = "[REDACTED]"


def scrub_sentry_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    return scrub_value(event)


def scrub_value(value: Any, parent_key: str | None = None) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = key.lower()
            if _is_sensitive_key(key_lower):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = scrub_value(item, key_lower)
        return cleaned

    if isinstance(value, list):
        return [scrub_value(item, parent_key) for item in value]

    if isinstance(value, tuple):
        return tuple(scrub_value(item, parent_key) for item in value)

    if isinstance(value, str):
        return scrub_text(value, parent_key)

    return value


def scrub_text(text: str, parent_key: str | None = None) -> str:
    if parent_key and _is_sensitive_key(parent_key):
        return REDACTED

    if "bearer " in text.lower():
        return REDACTED

    if text.startswith("http://") or text.startswith("https://"):
        return _scrub_url(text)

    return text


def _scrub_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if not parts.query:
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))

        filtered = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            filtered.append((key, REDACTED if _is_sensitive_key(key.lower()) else value))

        return urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(filtered, doseq=True),
            parts.fragment,
        ))
    except Exception:
        return url


def _is_sensitive_key(key: str) -> bool:
    return key in SENSITIVE_KEYS or any(fragment in key for fragment in ("token", "secret", "password", "cookie", "auth", "key"))
