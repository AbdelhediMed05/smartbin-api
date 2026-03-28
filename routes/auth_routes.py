from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr

from limiter import limiter
from services import auth_service
from validators import EmailField, PasswordField, RefreshTokenField, UsernameField

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request schemas ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """
    OWASP A03: extra="forbid" rejects unexpected fields (parameter pollution).
    Field types enforce max lengths before the service layer is reached.
    """
    model_config = ConfigDict(extra="forbid")

    email:    EmailStr     = EmailField          # type: ignore[assignment]
    password: PasswordField                       # max 128 chars — bcrypt-safe
    username: UsernameField                       # 3–20 chars; regex in service


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email:    EmailStr     = EmailField          # type: ignore[assignment]
    password: PasswordField                       # max 128 chars


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: RefreshTokenField              # max 2048 chars — JWT-safe


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")                        # IP-based: blocks bulk sign-up
async def register(request: Request, response: Response, body: RegisterRequest):
    return auth_service.register(body.email, body.password, body.username)


@router.post("/login")
@limiter.limit("5/minute")                        # IP-based: slows credential stuffing
async def login(request: Request, response: Response, body: LoginRequest):
    return auth_service.login(body.email, body.password)


@router.post("/refresh")
@limiter.limit("10/minute")                       # IP-based: refresh is frequent but bounded
async def refresh_token(request: Request, response: Response, body: RefreshRequest):
    return auth_service.refresh_token(body.refresh_token)


@router.post("/logout")
@limiter.limit("20/minute")                       # IP-based: generous — logout must not be blocked
async def logout(request: Request, response: Response):
    """
    Logout does not require a valid JWT body check — the token is already
    in the Authorization header, validated by the Supabase session.
    We still rate-limit to prevent hammering the Supabase signOut endpoint.
    """
    # auth header presence is validated by Supabase internally; no need to
    # replicate here — a missing token results in a no-op sign-out.
    return auth_service.logout()
