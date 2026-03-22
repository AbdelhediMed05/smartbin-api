import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address
from db import supabase_svc, supabase_anon

from config import get_settings

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


# ── Validation helpers ────────────────────────────────────────────────────────

def validate_password(pw: str):
    if len(pw) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if not re.search(r"[A-Z]", pw):
        raise HTTPException(400, "Password must contain at least one uppercase letter.")
    if not re.search(r"\d", pw):
        raise HTTPException(400, "Password must contain at least one number.")

def validate_username(un: str):
    if not re.match(r"^[a-zA-Z0-9_]{3,20}$", un):
        raise HTTPException(400, "Username must be 3–20 alphanumeric characters (underscores allowed).")

# ── Request schemas ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    username: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
@limiter.limit("3/minute")
async def register(request: Request, body: RegisterRequest):
    validate_password(body.password)
    validate_username(body.username)

    try:
        res = supabase_anon.auth.sign_up({
            "email": body.email,
            "password": body.password,
            "options": {"data": {"username": body.username}},
        })
        if res.user is None:
            raise HTTPException(400, "Registration failed. Email may already be in use.")
    except Exception as e:
        detail = str(e)
        if "already" in detail.lower() or "duplicate" in detail.lower():
            raise HTTPException(409, "Email already registered.")
        raise HTTPException(400, f"Registration error: {detail}")

    return {"message": "Check your email to confirm registration."}


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest):
    # Check account lockout
    try:
        profile = supabase_svc.table("profiles").select(
            "failed_logins,locked_until,is_active"
        ).eq("id", (
            # We need to find by email — use a lookup via auth
            # Supabase doesn't expose email in profiles table by default
            # We attempt login first, handle failures
            "placeholder"
        )).execute()
    except Exception:
        pass  # Proceed to login attempt; lockout checked below via email

    # Attempt Supabase Auth login
    try:
        res = supabase_anon.auth.sign_in_with_password({
            "email": body.email,
            "password": body.password,
        })
    except Exception as e:
        _handle_failed_login(body.email)
        raise HTTPException(401, "Invalid email or password.")

    if res.user is None or res.session is None:
        _handle_failed_login(body.email)
        raise HTTPException(401, "Invalid email or password.")

    user_id = res.user.id

    # Check lockout AFTER getting user_id
    try:
        profile_res = supabase_svc.table("profiles").select(
            "failed_logins,locked_until,is_active"
        ).eq("id", user_id).single().execute()
        profile = profile_res.data

        if profile:
            if not profile.get("is_active", True):
                raise HTTPException(403, "Account is disabled.")

            locked_until = profile.get("locked_until")
            if locked_until:
                lu = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
                if lu > datetime.now(timezone.utc):
                    remaining = int((lu - datetime.now(timezone.utc)).total_seconds() / 60)
                    raise HTTPException(423, f"Account locked. Try again in {remaining} minute(s).")

            # Reset failed logins on success
            supabase_svc.table("profiles").update({
                "failed_logins": 0,
                "locked_until": None,
            }).eq("id", user_id).execute()
    except HTTPException:
        raise
    except Exception:
        pass  # Profile issues shouldn't block login

    return {
        "access_token":  res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "token_type":    "bearer",
        "expires_in":    1800,
    }


def _handle_failed_login(email: str):
    """Increment failed_logins and lock account after 5 failures."""
    try:
        from datetime import timedelta
        # Use admin getUserByEmail instead of listing all users
        user = supabase_svc.auth.admin.get_user_by_email(email)
        if not user or not user.user:
            return
        profile_res = supabase_svc.table("profiles").select(
            "id,failed_logins"
        ).eq("id", user.user.id).single().execute()
        profile = profile_res.data
        if not profile:
            return
        new_count = (profile.get("failed_logins") or 0) + 1
        update = {"failed_logins": new_count}
        if new_count >= 5:
            update["locked_until"] = (
                datetime.now(timezone.utc) + timedelta(minutes=15)
            ).isoformat()
        supabase_svc.table("profiles").update(update).eq("id", user.user.id).execute()
    except Exception:
        pass  # Don't expose lockout errors


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh_token(request: Request, body: RefreshRequest):
    try:
        res = supabase_anon.auth.refresh_session(body.refresh_token)
        if res.session is None:
            raise HTTPException(401, "Invalid or expired refresh token.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Token refresh failed.")

    return {
        "access_token":  res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "expires_in":    1800,
    }


@router.post("/logout")
async def logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing token.")
    token = auth_header.split(" ", 1)[1]
    try:
        supabase_anon.auth.sign_out()
    except Exception:
        pass
    return {"message": "Logged out."}
