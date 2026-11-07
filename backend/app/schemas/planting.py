"""Planting batch and crop health assessment schemas (Modules 12 & 22)."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.planting import HealthRating, PlantingStatus, StressType


class PlantingBatchCreate(BaseModel):
    farm_id: int
    zone_id: int
    crop_id: int
    batch_code: str = Field(min_length=1, max_length=48)
    planting_date: date
    variety_name: str = Field(default="", max_length=120)
    area_planted_ha: Decimal | None = Field(default=None, gt=0)
    plant_density_per_m2: Decimal | None = Field(default=None, gt=0)
    expected_maturity_days_override: int | None = Field(default=None, gt=10, le=730)
    notes: str = Field(default="", max_length=4000)


class PlantingBatchUpdate(BaseModel):
    status: PlantingStatus | None = None
    actual_harvest_date: date | None = None
    actual_yield_kg: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=4000)


class PlantingBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    farm_id: int
    zone_id: int
    crop_id: int
    current_growth_stage_id: int | None = None
    batch_code: str
    variety_name: str
    planting_date: date
    actual_harvest_date: date | None = None
    status: PlantingStatus
    accumulated_gdd: Decimal
    expected_maturity_days: int
    predicted_maturity_date: date
    harvest_window_start: date
    harvest_window_end: date
    area_planted_ha: Decimal | None = None
    plant_density_per_m2: Decimal | None = None
    actual_yield_kg: Decimal | None = None
    notes: str
    created_at: datetime


class PlantingBatchListOut(BaseModel):
    items: list[PlantingBatchOut]


# ---------------------------------------------------------------------------
# Health Assessment Schemas
# ---------------------------------------------------------------------------

class CropHealthAssessmentCreate(BaseModel):
    planting_batch_id: int
    health_rating: HealthRating = HealthRating.healthy
    stress_type: StressType = StressType.none
    affected_area_pct: Decimal | None = Field(default=None, ge=0, le=100)
    symptoms_description: str = Field(default="", max_length=2000)
    recommended_action: str = Field(default="", max_length=2000)
    image_url: str = Field(default="", max_length=512)
    notes: str = Field(default="", max_length=4000)


class CropHealthAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    planting_batch_id: int
    farm_id: int
    zone_id: int
    assessed_by_user_id: int
    assessed_at: datetime
    health_rating: HealthRating
    stress_type: StressType
    affected_area_pct: Decimal | None = None
    symptoms_description: str
    recommended_action: str
    image_url: str
    notes: str


class CropHealthAssessmentListOut(BaseModel):
    items: list[CropHealthAssessmentOut]
