"""Module 1 — role/permission endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.core.permissions import PERMISSIONS
from app.models.user import Role
from app.schemas.user import PermissionOut, RoleOut, RolePermissionsUpdate
from app.services import audit_service, rbac_service

router = APIRouter()

RequiresRoleRead = Annotated[set[str], Depends(require_permissions("role.read"))]
RequiresRoleManage = Annotated[set[str], Depends(require_permissions("role.manage"))]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: DbSession, _: RequiresRoleRead):
    roles = db.query(Role).order_by(Role.code).all()
    return [
        RoleOut(
            code=r.code,
            name=r.name,
            description=r.description,
            permissions=sorted(p.code for p in r.permissions),
        )
        for r in roles
    ]


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(db: DbSession, _: RequiresRoleRead):
    from app.models.user import Permission

    perms = db.query(Permission).order_by(Permission.code).all()
    return [PermissionOut.model_validate(p) for p in perms]


@router.patch("/roles/{role_code}/permissions", response_model=RoleOut)
def update_role_permissions(
    role_code: str,
    payload: RolePermissionsUpdate,
    request: Request,
    db: DbSession,
    _: RequiresRoleManage,
    current_user: CurrentUser,
):
    role = rbac_service.get_role(db, role_code)
    if role is None:
        raise NotFoundError(f"role '{role_code}' does not exist")
    unknown = [p for p in payload.permissions if p not in PERMISSIONS]
    if unknown:
        raise ValidationError(f"unknown permission codes: {', '.join(unknown)}")
    if role_code == "admin" and "role.manage" not in payload.permissions:
        raise BusinessRuleError(
            "the admin role must retain role.manage or the system becomes unmanageable"
        )
    from app.models.user import Permission

    role.permissions = (
        db.query(Permission).filter(Permission.code.in_(payload.permissions)).all()
    )
    audit_service.log(
        db,
        user_id=current_user.id,
        actor_label=current_user.email,
        action="role.update_permissions",
        resource_type="role",
        resource_id=role.id,
        details={"permissions": sorted(payload.permissions)},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(role)
    return RoleOut(
        code=role.code,
        name=role.name,
        description=role.description,
        permissions=sorted(p.code for p in role.permissions),
    )
