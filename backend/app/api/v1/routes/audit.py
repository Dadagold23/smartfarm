"""Audit log endpoints (security requirement: auditable activities)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, require_permissions
from app.core.permissions import satisfies
from app.models.audit import AuditLog
from app.schemas.common import AuditLogOut

router = APIRouter()

RequiresAuditRead = Annotated[set[str], Depends(require_permissions("audit.read"))]


@router.get("", response_model=dict)
def list_audit_logs(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresAuditRead,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: int = Query(0, ge=0),
    action: str | None = None,
    resource_type: str | None = None,
):
    q = db.query(AuditLog)
    if not satisfies("audit.read.all", held):
        q = q.filter(AuditLog.user_id == current_user.id)
    if action:
        q = q.filter(AuditLog.action == action)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    total = q.count()
    items = q.order_by(AuditLog.id.desc()).limit(limit).offset(offset).all()
    return {
        "items": [AuditLogOut.model_validate(a).model_dump(mode="json") for a in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }
