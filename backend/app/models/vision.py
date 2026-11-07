"""Module 3 & Module 19 — AI Crop Identification and Weed Detection.

Stores computer vision plant identification requests, extracted visual features,
species classification with confidence scores, weed threat assessments
(infestation severity, competition risk), and agronomist verification records.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class IdentificationType(str, enum.Enum):
    crop = "crop"
    weed = "weed"
    mixed = "mixed"
    plant_disease = "plant_disease"


class WeedInfestationLevel(str, enum.Enum):
    none = "none"
    low = "low"
    moderate = "moderate"
    high = "high"
    critical = "critical"


class WeedCompetitionRisk(str, enum.Enum):
    none = "none"
    low = "low"
    moderate = "moderate"
    high = "high"


class VerificationStatus(str, enum.Enum):
    pending = "pending"
    verified_correct = "verified_correct"
    corrected = "corrected"
    rejected = "rejected"


class PlantIdentification(Base, TimestampMixin):
    """Computer vision inference log and human verification record."""

    __tablename__ = "plant_identifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int | None] = mapped_column(
        ForeignKey("farms.id", ondelete="SET NULL"), index=True, nullable=True
    )
    zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("irrigation_zones.id", ondelete="SET NULL"), index=True, nullable=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    # Image asset metadata
    image_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), default="image/jpeg", nullable=False)

    identification_type: Mapped[IdentificationType] = mapped_column(
        Enum(IdentificationType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=IdentificationType.crop,
    )

    # Primary predicted crop/plant
    predicted_crop_id: Mapped[int | None] = mapped_column(
        ForeignKey("crop_species.id", ondelete="SET NULL"), nullable=True
    )
    predicted_species_name: Mapped[str] = mapped_column(String(160), nullable=False)
    predicted_common_name: Mapped[str] = mapped_column(String(120), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)  # 0.000 to 1.000

    # Weed-specific analysis (Module 19)
    is_weed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    weed_species_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    weed_infestation_level: Mapped[WeedInfestationLevel] = mapped_column(
        Enum(WeedInfestationLevel, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=WeedInfestationLevel.none,
    )
    weed_competition_risk: Mapped[WeedCompetitionRisk] = mapped_column(
        Enum(WeedCompetitionRisk, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=WeedCompetitionRisk.none,
    )
    estimated_weed_coverage_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    # Growth stage assessment
    growth_stage_prediction: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Scientific feature analytics and candidate rankings
    alternative_predictions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    feature_analysis_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    # Agronomist verification flow
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=VerificationStatus.pending,
    )
    verified_crop_id: Mapped[int | None] = mapped_column(
        ForeignKey("crop_species.id", ondelete="SET NULL"), nullable=True
    )
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verification_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Relationships
    predicted_crop: Mapped["CropSpecies | None"] = relationship(  # noqa: F821
        foreign_keys=[predicted_crop_id]
    )
    verified_crop: Mapped["CropSpecies | None"] = relationship(  # noqa: F821
        foreign_keys=[verified_crop_id]
    )
    user: Mapped["User"] = relationship(foreign_keys=[user_id])  # noqa: F821
    verified_by_user: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[verified_by_user_id]
    )
