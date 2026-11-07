"""Module 5 extension — Soil profiles and soil physical properties.

Provides soil texture classifications, hydraulic properties (field capacity,
wilting point, saturation, hydraulic conductivity), and chemical baselines (pH,
EC) needed for scientific FAO-56 soil-water balance and irrigation scheduling.
All default parameters are grounded in USDA Soil Conservation Service and
FAO-56 Table 19 published physical characteristics.
"""

import enum
from decimal import Decimal

from sqlalchemy import (
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class SoilTextureType(str, enum.Enum):
    sand = "sand"
    loamy_sand = "loamy_sand"
    sandy_loam = "sandy_loam"
    loam = "loam"
    silt_loam = "silt_loam"
    silt = "silt"
    sandy_clay_loam = "sandy_clay_loam"
    clay_loam = "clay_loam"
    silty_clay_loam = "silty_clay_loam"
    sandy_clay = "sandy_clay"
    silty_clay = "silty_clay"
    clay = "clay"


# FAO-56 Table 19 / USDA Soil Taxonomy hydraulic benchmarks:
# (field_capacity_vol_fraction, wilting_point_vol_fraction, sat_hydraulic_cond_mm_hr)
USDA_SOIL_DEFAULTS: dict[SoilTextureType, tuple[Decimal, Decimal, Decimal]] = {
    SoilTextureType.sand: (Decimal("0.12"), Decimal("0.05"), Decimal("50.0")),
    SoilTextureType.loamy_sand: (Decimal("0.14"), Decimal("0.06"), Decimal("30.0")),
    SoilTextureType.sandy_loam: (Decimal("0.18"), Decimal("0.08"), Decimal("20.0")),
    SoilTextureType.loam: (Decimal("0.27"), Decimal("0.12"), Decimal("10.0")),
    SoilTextureType.silt_loam: (Decimal("0.31"), Decimal("0.13"), Decimal("6.5")),
    SoilTextureType.silt: (Decimal("0.30"), Decimal("0.09"), Decimal("5.0")),
    SoilTextureType.sandy_clay_loam: (Decimal("0.27"), Decimal("0.17"), Decimal("4.5")),
    SoilTextureType.clay_loam: (Decimal("0.32"), Decimal("0.18"), Decimal("3.5")),
    SoilTextureType.silty_clay_loam: (Decimal("0.38"), Decimal("0.22"), Decimal("2.0")),
    SoilTextureType.sandy_clay: (Decimal("0.36"), Decimal("0.25"), Decimal("1.5")),
    SoilTextureType.silty_clay: (Decimal("0.41"), Decimal("0.27"), Decimal("1.0")),
    SoilTextureType.clay: (Decimal("0.40"), Decimal("0.28"), Decimal("0.5")),
}


class SoilProfile(Base, TimestampMixin, SoftDeleteMixin):
    """Soil physical and hydraulic properties of an agricultural zone or farm."""

    __tablename__ = "soil_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    texture_type: Mapped[SoilTextureType] = mapped_column(
        Enum(SoilTextureType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=SoilTextureType.loam,
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Volumetric water content fractions (m3/m3 or %)
    # theta_FC: volumetric moisture content at field capacity (approx -33 kPa)
    field_capacity: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    # theta_WP: volumetric moisture content at permanent wilting point (approx -1500 kPa)
    wilting_point: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    # theta_SAT: saturation moisture content (total porosity)
    saturation: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    # Infiltration / saturated hydraulic conductivity (mm/hour)
    intake_rate_mm_per_hour: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )

    # Chemical baselines
    ph: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    electrical_conductivity_ds_m: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    organic_matter_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    farm: Mapped["Farm"] = relationship(back_populates="soil_profiles")  # noqa: F821
    zones: Mapped[list["IrrigationZone"]] = relationship(back_populates="soil_profile")  # noqa: F821

    @property
    def available_water_capacity(self) -> Decimal:
        """Total Available Water capacity (theta_FC - theta_WP) in m3/m3 fraction."""
        return self.field_capacity - self.wilting_point
