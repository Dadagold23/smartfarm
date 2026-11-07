"""User and role management schemas (Module 1)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    """Admin-created user (can be given any role set)."""

    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role_codes: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    email: EmailStr | None = None
    is_active: bool | None = None


class UserRoleUpdate(BaseModel):
    role_codes: list[str]


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[str] = []

    @field_validator("roles", mode="before")
    @classmethod
    def _roles_to_codes(cls, v):
        # ORM relationship yields Role objects; API exposes codes.
        return [r.code if hasattr(r, "code") else r for r in v or []]


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    description: str
    permissions: list[str] = []


class RolePermissionsUpdate(BaseModel):
    permissions: list[str]


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    description: str
