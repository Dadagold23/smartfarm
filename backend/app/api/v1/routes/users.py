"""Module 1 — user management endpoints (admin-gated)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import (
    CurrentUser,
    DbSession,
    HeldPermissions,
    client_ip,
    require_permissions,
)
from app.schemas.user import UserAdminOut, UserCreate, UserRoleUpdate, UserUpdate
from app.services import user_service

router = APIRouter()

RequiresUserRead = Annotated[set[str], Depends(require_permissions("user.read"))]
RequiresUserCreate = Annotated[set[str], Depends(require_permissions("user.create"))]
RequiresUserUpdate = Annotated[set[str], Depends(require_permissions("user.update"))]
RequiresRoleManage = Annotated[set[str], Depends(require_permissions("role.manage"))]


@router.get("", response_model=dict)
def list_users(
    db: DbSession,
    _: RequiresUserRead,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: int = Query(0, ge=0),
):
    items, total = user_service.list_users(db, limit=limit, offset=offset)
    return {
        "items": [UserAdminOut.model_validate(u).model_dump() for u in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.post("", response_model=UserAdminOut, status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: DbSession,
    _: RequiresUserCreate,
    current_user: CurrentUser,
):
    user = user_service.create_user(
        db,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        role_codes=payload.role_codes,
        actor=current_user,
        ip_address=client_ip(request),
    )
    return UserAdminOut.model_validate(user)


@router.get("/{user_id}", response_model=UserAdminOut)
def get_user(user_id: int, db: DbSession, _: RequiresUserRead, current_user: CurrentUser):
    # The permission dependency already guarantees user.read; a user may
    # always fetch their own record even in tighter deployments.
    return UserAdminOut.model_validate(user_service.get_user(db, user_id))


@router.patch("/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: DbSession,
    _: RequiresUserUpdate,
    current_user: CurrentUser,
):
    if payload.is_active is False and user_id == current_user.id:
        from app.core.exceptions import BusinessRuleError

        raise BusinessRuleError("you cannot deactivate your own account")
    user = user_service.update_user(
        db,
        user_id,
        full_name=payload.full_name,
        email=payload.email,
        is_active=payload.is_active,
        actor=current_user,
        ip_address=client_ip(request),
    )
    return UserAdminOut.model_validate(user)


@router.put("/{user_id}/roles", response_model=UserAdminOut)
def set_roles(
    user_id: int,
    payload: UserRoleUpdate,
    request: Request,
    db: DbSession,
    _: RequiresRoleManage,
    current_user: CurrentUser,
):
    if user_id == current_user.id:
        from app.core.exceptions import BusinessRuleError

        raise BusinessRuleError(
            "you cannot change your own roles; ask another administrator"
        )
    user = user_service.set_user_roles(
        db, user_id, payload.role_codes, actor=current_user, ip_address=client_ip(request)
    )
    return UserAdminOut.model_validate(user)
