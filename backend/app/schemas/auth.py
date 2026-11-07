"""Auth-related schemas (Module 1)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class RoleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    is_active: bool
    last_login_at: datetime | None
    roles: list[RoleBrief]
    # Effective permission codes (flattened from roles). The frontend uses
    # these to hide actions the API would refuse anyway (server enforces).
    permissions: list[str] = []
    created_at: datetime


def user_out(user) -> "UserOut":
    from app.services.rbac_service import get_user_permission_codes

    return UserOut(
        **{
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "last_login_at": user.last_login_at,
            "created_at": user.created_at,
            "roles": [RoleBrief.model_validate(r) for r in user.roles],
            "permissions": sorted(get_user_permission_codes(user)),
        }
    )


class AuthResponse(BaseModel):
    tokens: TokenPair
    user: UserOut
