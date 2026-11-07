"""Module 4 — Agricultural Research and Crop Knowledge Database.

Stores botanical characteristics, growth stages, FAO-56 crop coefficients (Kc),
rooting depths, depletion fractions (p), thermal time requirements (GDD),
and salinity/pH thresholds sourced from peer-reviewed agricultural research
(FAO Irrigation and Drainage Paper 56, IITA, USDA ARS).
"""

import enum
from decimal import Decimal

from sqlalchemy import (
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class CropCategory(str, enum.Enum):
    cereal = "cereal"
    vegetable = "vegetable"
    legume = "legume"
    fruit = "fruit"
    tuber = "tuber"
    oilseed = "oilseed"
    fiber = "fiber"
    fodder = "fodder"
    other = "other"


class GrowthStageName(str, enum.Enum):
    initial = "initial"
    development = "development"
    mid_season = "mid_season"
    late_season = "late_season"


class CropSpecies(Base, TimestampMixin, SoftDeleteMixin):
    """Agronomic crop specification with validated scientific parameters."""

    __tablename__ = "crop_species"

    id: Mapped[int] = mapped_column(primary_key=True)
    common_name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    scientific_name: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    category: Mapped[CropCategory] = mapped_column(
        Enum(CropCategory, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=CropCategory.cereal,
    )
    variety: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Root depth parameters (m) per FAO-56 Table 22
    min_root_depth_m: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    max_root_depth_m: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)

    # Soil water depletion fraction for no stress (p) per FAO-56 Table 22
    # Typically 0.20 to 0.70; fraction of TAW that can be depleted before stress occurs
    depletion_fraction_p: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    # Yield response factor Ky (FAO-33 / FAO-56) indicating crop sensitivity to water deficit
    yield_response_factor_ky: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)

    # Temperature parameters for Growing Degree Day (GDD) calculation (°C)
    base_temperature_c: Mapped[Decimal] = mapped_column(Numeric(4, 1), default=Decimal("10.0"), nullable=False)
    cutoff_temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)

    # Typical life cycle duration in days
    standard_cycle_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # Soil chemical suitability
    optimal_ph_min: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    optimal_ph_max: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    salinity_threshold_ec_ds_m: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)

    # Verification and provenance
    research_source: Mapped[str] = mapped_column(String(255), default="FAO Irrigation & Drainage Paper 56", nullable=False)
    is_verified: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Relationships
    growth_stages: Mapped[list["CropGrowthStage"]] = relationship(
        back_populates="crop", cascade="all, delete-orphan", lazy="selectin", order_by="CropGrowthStage.stage_order"
    )
    plantings: Mapped[list["PlantingBatch"]] = relationship(  # noqa: F821
        back_populates="crop", lazy="selectin"
    )


class CropGrowthStage(Base, TimestampMixin):
    """Specific developmental stage with Kc coefficient and duration for a crop."""

    __tablename__ = "crop_growth_stages"
    __table_args__ = (
        UniqueConstraint("crop_id", "stage_name", name="uq_crop_growth_stage"),
        UniqueConstraint("crop_id", "stage_order", name="uq_crop_growth_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crop_id: Mapped[int] = mapped_column(
        ForeignKey("crop_species.id", ondelete="CASCADE"), index=True, nullable=False
    )
    stage_name: Mapped[GrowthStageName] = mapped_column(
        Enum(GrowthStageName, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    stage_order: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 to 4
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_pct_of_cycle: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    accumulated_gdd_target: Mapped[Decimal | None] = mapped_column(Numeric(7, 1), nullable=True)

    # FAO-56 Crop Coefficient Kc for this stage (e.g. Kc_ini, Kc_mid, Kc_end)
    kc_coefficient: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)

    # Root depth at end of this stage (m)
    stage_root_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)

    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    crop: Mapped["CropSpecies"] = relationship(back_populates="growth_stages")
