"""Plant identification and weed detection schemas (Modules 3 & 19)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.vision import (
    IdentificationType,
    VerificationStatus,
    WeedCompetitionRisk,
    WeedInfestationLevel,
)
from app.schemas.common import PageMeta


class PlantIdentificationVerifyIn(BaseModel):
    status: VerificationStatus
    verified_crop_id: int | None = None
    notes: str = Field(default="", max_length=2000)


class PlantIdentificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    farm_id: int | None = None
    zone_id: int | None = None
    user_id: int
    image_filename: str
    image_url: str
    file_size_bytes: int
    mime_type: str
    identification_type: IdentificationType
    predicted_crop_id: int | None = None
    predicted_species_name: str
    predicted_common_name: str
    confidence_score: Decimal
    is_weed: bool
    weed_species_name: str
    weed_infestation_level: WeedInfestationLevel
    weed_competition_risk: WeedCompetitionRisk
    estimated_weed_coverage_pct: Decimal | None = None
    growth_stage_prediction: str
    recommended_action: str
    alternative_predictions_json: str
    feature_analysis_json: str
    verification_status: VerificationStatus
    verified_crop_id: int | None = None
    verified_by_user_id: int | None = None
    verified_at: datetime | None = None
    verification_notes: str
    created_at: datetime


class PlantIdentificationListOut(BaseModel):
    items: list[PlantIdentificationOut]
    meta: PageMeta
