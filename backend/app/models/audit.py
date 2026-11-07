"""Audit log model (security requirement: all state changes recorded)."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # NULL user_id + actor_label "system" is used for bootstrap operations
    # (RBAC sync, admin creation) that run without a request context.
