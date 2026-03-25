from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    username: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(request: Request, body: RegisterRequest):
    return auth_service.register(body.email, body.password, body.username)


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest):
    return auth_service.login(body.email, body.password)


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh_token(request: Request, body: RefreshRequest):
    return auth_service.refresh_token(body.refresh_token)


@router.post("/logout")
async def logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing token.")
    return auth_service.logout()
