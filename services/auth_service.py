import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from config import get_settings
from domain.auth_policy import (
    ACCESS_TOKEN_EXPIRES_IN,
    FAILED_LOGIN_LIMIT,
    LOCKOUT_MINUTES,
    PASSWORD_MIN_LENGTH,
    REQUIRE_EMAIL_CONFIRMATION,
    USERNAME_PATTERN,
)
from repositories import auth_repository
from validators import PASSWORD_MAX

settings = get_settings()
logger   = logging.getLogger(__name__)


# ── Input validation helpers ──────────────────────────────────────────────────

def validate_password(password: str) -> None:
    """
    Server-side password policy enforcement.
    Max length is enforced here as a belt-and-suspenders check even though
    the Pydantic schema already enforces PASSWORD_MAX — the service layer
    must not assume the caller is a well-behaved FastAPI route.
    """
    # Max length: prevent long-password DoS (argon2 has no truncation unlike bcrypt)
    if len(password) > PASSWORD_MAX:
        raise HTTPException(400, f"Password must be at most {PASSWORD_MAX} characters.")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(400, f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(400, "Password must contain at least one uppercase letter.")
    if not re.search(r"\d", password):
        raise HTTPException(400, "Password must contain at least one number.")


def validate_username(username: str) -> None:
    if not re.match(USERNAME_PATTERN, username):
        raise HTTPException(
            400,
            "Username must be 3–20 alphanumeric characters (underscores allowed).",
        )


# ── Public service functions ──────────────────────────────────────────────────

def register(email: str, password: str, username: str) -> dict:
    validate_password(password)
    validate_username(username)

    email_redirect_to = f"{settings.frontend_url.rstrip('/')}/email-confirmed.html"

    try:
        res = auth_repository.sign_up(email, password, username, email_redirect_to=email_redirect_to)
        if res.user is None:
            # OWASP A05: do not expose the raw Supabase error — use a safe message.
            raise HTTPException(400, "Registration failed. Email may already be in use.")
    except HTTPException:
        raise
    except Exception as exc:
        detail = str(exc).lower()
        # Map known provider error patterns to safe, generic messages.
        # Never forward raw exception strings — they may contain internal detail.
        if "already" in detail or "duplicate" in detail or "exists" in detail:
            raise HTTPException(409, "Email already registered.")
        logger.warning("Registration error (not forwarded to client): %s", exc)
        raise HTTPException(400, "Registration failed. Please try again.")

    return {"message": "Check your email to confirm registration."}


def login(email: str, password: str) -> dict:
    try:
        res = auth_repository.sign_in(email, password)
    except Exception:
        # OWASP A07: same message whether email exists or not — prevents enumeration
        _handle_failed_login(email)
        raise HTTPException(401, "Invalid email or password.")

    if res.user is None or res.session is None:
        _handle_failed_login(email)
        raise HTTPException(401, "Invalid email or password.")

    if REQUIRE_EMAIL_CONFIRMATION and not _is_email_confirmed(res.user):
        _safe_sign_out()
        raise HTTPException(403, "Please confirm your email before signing in.")

    user_id = res.user.id

    try:
        profile = auth_repository.get_profile_login_state(user_id)
        if profile:
            if not profile.get("is_active", True):
                _safe_sign_out()
                raise HTTPException(403, "Account is disabled.")

            locked_until = profile.get("locked_until")
            if locked_until:
                lock_until_dt = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if lock_until_dt > now:
                    _safe_sign_out()
                    remaining = max(1, int((lock_until_dt - now).total_seconds() / 60))
                    raise HTTPException(
                        423, f"Account locked. Try again in {remaining} minute(s)."
                    )

            auth_repository.update_profile(user_id, {
                "failed_logins": 0,
                "locked_until": None,
            })
    except HTTPException:
        raise
    except Exception:
        # Profile check failure is non-fatal — log quietly and proceed
        logger.debug("Could not read profile lockout state for user %s", user_id)

    return {
        "access_token":  res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "token_type":    "bearer",
        "expires_in":    ACCESS_TOKEN_EXPIRES_IN,
    }


def refresh_token(token: str) -> dict:
    try:
        res = auth_repository.refresh_session(token)
        if res.session is None:
            raise HTTPException(401, "Invalid or expired refresh token.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Token refresh failed.")

    return {
        "access_token":  res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "expires_in":    ACCESS_TOKEN_EXPIRES_IN,
    }


def logout() -> dict:
    _safe_sign_out()
    return {"message": "Logged out."}


# ── Private helpers ───────────────────────────────────────────────────────────

def _handle_failed_login(email: str) -> None:
    """
    Increment failed-login counter; lock account after FAILED_LOGIN_LIMIT failures.
    Errors here are swallowed — never let a DB failure expose account existence.
    """
    try:
        user = auth_repository.get_user_by_email(email)
        if not user or not user.user:
            return   # email doesn't exist — return silently (no enumeration)

        profile = auth_repository.get_profile_failed_logins(user.user.id)
        if not profile:
            return

        new_count = (profile.get("failed_logins") or 0) + 1
        update: dict = {"failed_logins": new_count}
        if new_count >= FAILED_LOGIN_LIMIT:
            update["locked_until"] = (
                datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
            ).isoformat()

        auth_repository.update_profile(user.user.id, update)
    except Exception:
        pass   # silently — never reveal whether the user exists


def _safe_sign_out() -> None:
    try:
        auth_repository.sign_out()
    except Exception:
        pass


def _is_email_confirmed(user) -> bool:
    return bool(
        _read_field(user, "email_confirmed_at")
        or _read_field(user, "confirmed_at")
    )


def _read_field(obj, field_name: str):
    if isinstance(obj, dict):
        return obj.get(field_name)
    return getattr(obj, field_name, None)
