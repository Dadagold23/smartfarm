"""Module 1 — authentication endpoints."""

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, DbSession, client_ip
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
    user_out,
)
from app.services import user_service

router = APIRouter()


def _issue_tokens(user) -> TokenPair:
    role_codes = [r.code for r in user.roles]
    access, expires = create_access_token(
        subject=str(user.id), extra_claims={"roles": role_codes}
    )
    refresh, _ = create_refresh_token(subject=str(user.id))
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=expires)


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: DbSession):
    user = user_service.register_user(
        db,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        default_role_code=get_settings().DEFAULT_SELF_REGISTRATION_ROLE,
        ip_address=client_ip(request),
    )
    return AuthResponse(tokens=_issue_tokens(user), user=user_out(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: DbSession):
    user = user_service.authenticate(
        db, email=payload.email, password=payload.password, ip_address=client_ip(request)
    )
    return AuthResponse(tokens=_issue_tokens(user), user=user_out(user))


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession):
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
        subject = int(claims["sub"])
    except Exception:
        raise AuthenticationError("invalid refresh token") from None
    user = user_service.get_user(db, subject)
    if not user.is_active:
        raise AuthenticationError("account is deactivated")
    return _issue_tokens(user)


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser):
    return user_out(current_user)
