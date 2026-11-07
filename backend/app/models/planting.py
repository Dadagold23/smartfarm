"""Module 12 & Module 22 — Crop Lifecycle, Planting Batches and Health Monitoring.

Manages individual field planting batches per farm and irrigation zone,
accumulating Growing Degree Days (GDD) to calculate current growth stages,
absolute calendar maturity dates, harvest windows, and field health assessments.
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class PlantingStatus(str, enum.Enum):
    planned = "planned"
    active = "active"
    mature = "mature"
    harvested = "harvested"
    failed = "failed"
    dormant = "dormant"


class HealthRating(str, enum.Enum):
    healthy = "healthy"
    mild_stress = "mild_stress"
    moderate_stress = "moderate_stress"
    severe_stress = "severe_stress"
    critical = "critical"


class StressType(str, enum.Enum):
    none = "none"
    water_deficit = "water_deficit"
    water_excess = "water_excess"
    nutrient_deficiency = "nutrient_deficiency"
    heat_stress = "heat_stress"
    frost = "frost"
    disease = "disease"
    pest = "pest"
    weed_competition = "weed_competition"
    other = "other"


class PlantingBatch(Base, TimestampMixin, SoftDeleteMixin):
    """Field planting batch tracking crop growth and absolute maturity timeline."""

    __tablename__ = "planting_batches"
    __table_args__ = (
        UniqueConstraint("farm_id", "batch_code", name="uq_plantings_farm_batch_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_id: Mapped[int] = mapped_column(
        ForeignKey("irrigation_zones.id", ondelete="CASCADE"), index=True, nullable=False
    )
    crop_id: Mapped[int] = mapped_column(
        ForeignKey("crop_species.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    current_growth_stage_id: Mapped[int | None] = mapped_column(
        ForeignKey("crop_growth_stages.id", ondelete="SET NULL"), nullable=True
    )

    batch_code: Mapped[str] = mapped_column(String(48), nullable=False)
    variety_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    planting_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_harvest_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Dynamic lifecycle tracking
    status: Mapped[PlantingStatus] = mapped_column(
        Enum(PlantingStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PlantingStatus.active,
    )
    accumulated_gdd: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.0"), nullable=False
    )

    # Absolute calendar prediction dates (Module 22 requirement)
    expected_maturity_days: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    harvest_window_start: Mapped[date] = mapped_column(Date, nullable=False)
    harvest_window_end: Mapped[date] = mapped_column(Date, nullable=False)

    # Field properties
    area_planted_ha: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    plant_density_per_m2: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    actual_yield_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Relationships
    farm: Mapped["Farm"] = relationship(back_populates="plantings")  # noqa: F821
    zone: Mapped["IrrigationZone"] = relationship(back_populates="plantings")  # noqa: F821
    crop: Mapped["CropSpecies"] = relationship(back_populates="plantings")  # noqa: F821
    current_growth_stage: Mapped["CropGrowthStage | None"] = relationship()  # noqa: F821
    health_assessments: Mapped[list["CropHealthAssessment"]] = relationship(
        back_populates="planting_batch", cascade="all, delete-orphan", lazy="selectin"
    )
    schedules: Mapped[list["IrrigationSchedule"]] = relationship(  # noqa: F821
        back_populates="planting_batch", lazy="selectin"
    )


class CropHealthAssessment(Base, TimestampMixin):
    """Field observation log for crop health, disease, and stress symptoms."""

    __tablename__ = "crop_health_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    planting_batch_id: Mapped[int] = mapped_column(
        ForeignKey("planting_batches.id", ondelete="CASCADE"), index=True, nullable=False
    )
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_id: Mapped[int] = mapped_column(
        ForeignKey("irrigation_zones.id", ondelete="CASCADE"), index=True, nullable=False
    )
    assessed_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    assessed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    health_rating: Mapped[HealthRating] = mapped_column(
        Enum(HealthRating, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=HealthRating.healthy,
    )
    stress_type: Mapped[StressType] = mapped_column(
        Enum(StressType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=StressType.none,
    )

    affected_area_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    symptoms_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    planting_batch: Mapped["PlantingBatch"] = relationship(back_populates="health_assessments")
