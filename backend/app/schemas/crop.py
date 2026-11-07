"""Crop knowledge database and soil profile schemas (Modules 4 & 5)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.crop import CropCategory, GrowthStageName
from app.models.soil_profile import SoilTextureType
from app.schemas.common import PageMeta


class CropGrowthStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    crop_id: int
    stage_name: GrowthStageName
    stage_order: int
    duration_days: int
    duration_pct_of_cycle: Decimal | None = None
    kc_coefficient: Decimal
    stage_root_depth_m: Decimal | None = None
    description: str


class CropSpeciesBase(BaseModel):
    common_name: str = Field(min_length=2, max_length=120)
    scientific_name: str = Field(min_length=2, max_length=160)
    category: CropCategory = CropCategory.cereal
    variety: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=4000)
    min_root_depth_m: Decimal = Field(gt=0, le=5)
    max_root_depth_m: Decimal = Field(gt=0, le=5)
    depletion_fraction_p: Decimal = Field(gt=0, lt=1)
    yield_response_factor_ky: Decimal | None = Field(default=None, gt=0, le=3)
    base_temperature_c: Decimal = Field(ge=-5, le=30)
    cutoff_temperature_c: Decimal | None = Field(default=None, ge=15, le=50)
    standard_cycle_days: int = Field(gt=10, le=730)
    optimal_ph_min: Decimal | None = Field(default=None, ge=3, le=10)
    optimal_ph_max: Decimal | None = Field(default=None, ge=3, le=10)
    salinity_threshold_ec_ds_m: Decimal | None = Field(default=None, ge=0, le=30)
    research_source: str = Field(default="FAO-56", max_length=255)


class CropSpeciesCreate(CropSpeciesBase):
    pass


class CropSpeciesOut(CropSpeciesBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_verified: bool
    created_at: datetime
    growth_stages: list[CropGrowthStageOut] = []


class CropSpeciesListOut(BaseModel):
    items: list[CropSpeciesOut]
    meta: PageMeta


# ---------------------------------------------------------------------------
# Soil Profile Schemas
# ---------------------------------------------------------------------------

class SoilProfileCreate(BaseModel):
    farm_id: int
    name: str = Field(min_length=2, max_length=255)
    texture_type: SoilTextureType = SoilTextureType.loam
    description: str = Field(default="", max_length=2000)
    field_capacity: Decimal | None = Field(default=None, gt=0, lt=1)
    wilting_point: Decimal | None = Field(default=None, gt=0, lt=1)
    saturation: Decimal | None = Field(default=None, gt=0, lt=1)
    intake_rate_mm_per_hour: Decimal | None = Field(default=None, gt=0, le=200)
    ph: Decimal | None = Field(default=None, ge=3, le=10)
    electrical_conductivity_ds_m: Decimal | None = Field(default=None, ge=0, le=30)


class SoilProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    texture_type: SoilTextureType | None = None
    description: str | None = Field(default=None, max_length=2000)
    field_capacity: Decimal | None = Field(default=None, gt=0, lt=1)
    wilting_point: Decimal | None = Field(default=None, gt=0, lt=1)
    saturation: Decimal | None = Field(default=None, gt=0, lt=1)
    intake_rate_mm_per_hour: Decimal | None = Field(default=None, gt=0, le=200)
    ph: Decimal | None = Field(default=None, ge=3, le=10)
    electrical_conductivity_ds_m: Decimal | None = Field(default=None, ge=0, le=30)


class SoilProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    farm_id: int
    name: str
    texture_type: SoilTextureType
    description: str
    field_capacity: Decimal
    wilting_point: Decimal
    saturation: Decimal | None = None
    intake_rate_mm_per_hour: Decimal | None = None
    ph: Decimal | None = None
    electrical_conductivity_ds_m: Decimal | None = None
    created_at: datetime


class SoilProfileListOut(BaseModel):
    items: list[SoilProfileOut]
