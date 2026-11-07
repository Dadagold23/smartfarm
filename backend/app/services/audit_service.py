"""Audit trail writer (cross-cutting security requirement)."""

import json

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def log(
    db: Session,
    *,
    user_id: int | None,
    actor_label: str,
    action: str,
    resource_type: str = "",
    resource_id: str | int | None = None,
    details: dict | None = None,
    ip_address: str = "",
) -> AuditLog:
    """Append an audit entry. Callers commit; audit rows are never updated
    or deleted through application code (append-only by policy)."""
    entry = AuditLog(
        user_id=user_id,
        actor_label=actor_label[:255],
        action=action[:128],
        resource_type=resource_type[:64],
        resource_id=str(resource_id or ""),
        details_json=json.dumps(details or {}, default=str),
        ip_address=ip_address[:64],
    )
    db.add(entry)
    return entry


record_audit_event = log

