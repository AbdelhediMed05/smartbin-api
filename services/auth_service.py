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

settings = get_settings()


def validate_password(password: str):
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(400, f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(400, "Password must contain at least one uppercase letter.")
    if not re.search(r"\d", password):
        raise HTTPException(400, "Password must contain at least one number.")


def validate_username(username: str):
    if not re.match(USERNAME_PATTERN, username):
        raise HTTPException(400, "Username must be 3–20 alphanumeric characters (underscores allowed).")


def register(email: str, password: str, username: str) -> dict:
    validate_password(password)
    validate_username(username)
    email_redirect_to = f"{settings.frontend_url.rstrip('/')}/email-confirmed.html"

    try:
        res = auth_repository.sign_up(email, password, username, email_redirect_to=email_redirect_to)
        if res.user is None:
            raise HTTPException(400, "Registration failed. Email may already be in use.")
    except Exception as e:
        detail = str(e)
        if "already" in detail.lower() or "duplicate" in detail.lower():
            raise HTTPException(409, "Email already registered.")
        raise HTTPException(400, f"Registration error: {detail}")

    return {"message": "Check your email to confirm registration."}


def login(email: str, password: str) -> dict:
    try:
        res = auth_repository.sign_in(email, password)
    except Exception:
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
                    raise HTTPException(423, f"Account locked. Try again in {remaining} minute(s).")

            auth_repository.update_profile(user_id, {
                "failed_logins": 0,
                "locked_until": None,
            })
    except HTTPException:
        raise
    except Exception:
        pass

    return {
        "access_token": res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRES_IN,
    }


def refresh_token(refresh_token: str) -> dict:
    try:
        res = auth_repository.refresh_session(refresh_token)
        if res.session is None:
            raise HTTPException(401, "Invalid or expired refresh token.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Token refresh failed.")

    return {
        "access_token": res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "expires_in": ACCESS_TOKEN_EXPIRES_IN,
    }


def logout() -> dict:
    _safe_sign_out()
    return {"message": "Logged out."}


def _handle_failed_login(email: str):
    try:
        user = auth_repository.get_user_by_email(email)
        if not user or not user.user:
            return

        profile = auth_repository.get_profile_failed_logins(user.user.id)
        if not profile:
            return

        new_count = (profile.get("failed_logins") or 0) + 1
        update = {"failed_logins": new_count}
        if new_count >= FAILED_LOGIN_LIMIT:
            update["locked_until"] = (
                datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
            ).isoformat()

        auth_repository.update_profile(user.user.id, update)
    except Exception:
        pass


def _safe_sign_out():
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
