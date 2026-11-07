"""Irrigation schedule and water balance schemas (Module 7)."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.schedule import ScheduleReason, ScheduleStatus


class ScheduleCalculateIn(BaseModel):
    farm_id: int
    zone_id: int
    target_date: date | None = None


class ScheduleApproveIn(BaseModel):
    notes: str = Field(default="", max_length=1000)


class ScheduleRejectIn(BaseModel):
    reason: str = Field(default="", max_length=1000)


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    farm_id: int
    zone_id: int
    planting_batch_id: int | None = None
    approved_by_user_id: int | None = None
    calculation_date: date
    target_date: date
    reference_et0_mm: Decimal
    crop_kc: Decimal
    crop_etc_mm: Decimal
    forecast_precipitation_mm: Decimal
    effective_precipitation_mm: Decimal
    current_soil_moisture_pct: Decimal | None = None
    root_depth_m: Decimal
    total_available_water_mm: Decimal
    readily_available_water_mm: Decimal
    root_zone_depletion_mm: Decimal
    water_stress_coefficient_ks: Decimal
    net_irrigation_requirement_mm: Decimal
    application_efficiency_pct: Decimal
    gross_irrigation_requirement_mm: Decimal
    recommended_runtime_minutes: int
    recommended_volume_m3: Decimal
    status: ScheduleStatus
    reason: ScheduleReason
    recommended_start_time: datetime | None = None
    recommended_end_time: datetime | None = None
    safety_checks_passed: bool
    weather_skip_flag: bool
    calculation_metadata_json: str
    created_at: datetime


class ScheduleListOut(BaseModel):
    items: list[ScheduleOut]
