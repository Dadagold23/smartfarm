"""Module 10 — AI agricultural advisory schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdvisoryGenerateIn(BaseModel):
    farm_id: int
    zone_id: int | None = None
    focus: str | None = Field(default=None, max_length=500)


class AdvisoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: int
    zone_id: int | None = None
    risk_level: str
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    source: str = "farm_state"
    generated_at: datetime
