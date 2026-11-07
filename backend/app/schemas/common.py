"""Audit-log and shared schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    actor_label: str
    action: str
    resource_type: str
    resource_id: str
    details_json: str
    ip_address: str
    created_at: datetime


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
