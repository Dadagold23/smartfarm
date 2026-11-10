"""Module 2 — Farm and irrigation-zone models."""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
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


class WaterSourceType(str, enum.Enum):
    borehole = "borehole"
    well = "well"
    reservoir = "reservoir"
    river = "river"
    canal = "canal"
    municipal = "municipal"
    harvested_rainwater = "harvested_rainwater"
    desalinated = "desalinated"
    other = "other"


class FarmStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class ZoneStatus(str, enum.Enum):
    active = "active"
    maintenance = "maintenance"
    disabled = "disabled"


class ZoneControlMode(str, enum.Enum):
    manual = "manual"
    automatic = "automatic"
    semi_automatic = "semi_automatic"
    scheduled = "scheduled"
    sensor_triggered = "sensor_triggered"
    weather_adjusted = "weather_adjusted"


class Farm(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "farms"
    __table_args__ = (
        UniqueConstraint("owner_id", "code", name="uq_farms_owner_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Location. `geometry` holds optional GeoJSON (polygon or point) as text
    # on SQLite; on PostgreSQL this column becomes PostGIS GEOGRAPHY via the
    # Phase 6 migration (see docs/ARCHITECTURE.md §Database).
    country: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    region: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    locality: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    elevation_m: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    geometry: Mapped[str | None] = mapped_column(Text, nullable=True)

    area_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    water_source: Mapped[WaterSourceType] = mapped_column(
        Enum(WaterSourceType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=WaterSourceType.other,
    )
    status: Mapped[FarmStatus] = mapped_column(
        Enum(FarmStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=FarmStatus.active,
    )

    owner: Mapped["User"] = relationship(  # noqa: F821
        back_populates="owned_farms", foreign_keys=[owner_id]
    )
    zones: Mapped[list["IrrigationZone"]] = relationship(
        back_populates="farm", cascade="all, delete-orphan", lazy="selectin"
    )
    # Phase 2 (Modules 5/6/9): registered IoT devices on this farm.
    devices: Mapped[list["Device"]] = relationship(  # noqa: F821
        back_populates="farm", lazy="selectin"
    )
    # Phase 3 (Modules 5, 7, 12): soil profiles, plantings, and irrigation schedules.
    soil_profiles: Mapped[list["SoilProfile"]] = relationship(  # noqa: F821
        back_populates="farm", cascade="all, delete-orphan", lazy="selectin"
    )
    plantings: Mapped[list["PlantingBatch"]] = relationship(  # noqa: F821
        back_populates="farm", cascade="all, delete-orphan", lazy="selectin"
    )
    schedules: Mapped[list["IrrigationSchedule"]] = relationship(  # noqa: F821
        back_populates="farm", cascade="all, delete-orphan", lazy="selectin"
    )

    # ---------------- Later-phase extension points (no fake data) ---------
    # water_usage_records  (Module 11) — added in Phase 4 migration


class IrrigationZone(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "irrigation_zones"
    __table_args__ = (
        UniqueConstraint("farm_id", "code", name="uq_zones_farm_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    area_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ZoneStatus] = mapped_column(
        Enum(ZoneStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ZoneStatus.active,
    )
    # Zone geometry (GeoJSON text on SQLite, PostGIS GEOGRAPHY in production).
    geometry: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Manual water application rate cap — an OPERATOR-ENTERED configured limit,
    # not an invented agricultural parameter. Actual agronomic rates come from
    # the ET engine (Module 7, Phase 3). Nullable on purpose: NULL = "not set
    # yet", which downstream logic must treat as "cannot schedule".
    max_application_mm_per_hour: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    control_mode: Mapped[ZoneControlMode] = mapped_column(
        Enum(ZoneControlMode, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ZoneControlMode.automatic,
    )
    is_running: Mapped[bool] = mapped_column(default=False, nullable=False)
    emergency_stop: Mapped[bool] = mapped_column(default=False, nullable=False)
    current_flow_lpm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    pressure_bar: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Phase 3: Soil physical profile for water retention (field capacity, wilting point)
    soil_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("soil_profiles.id", ondelete="SET NULL"), nullable=True
    )

    farm: Mapped["Farm"] = relationship(back_populates="zones")
    # Phase 2: soil probes mounted on this zone (Device.zone_id).
    devices: Mapped[list["Device"]] = relationship(  # noqa: F821
        back_populates="zone", lazy="selectin"
    )
    # Phase 3: soil profile, active plantings, and zone schedules
    soil_profile: Mapped["SoilProfile | None"] = relationship(  # noqa: F821
        back_populates="zones"
    )
    plantings: Mapped[list["PlantingBatch"]] = relationship(  # noqa: F821
        back_populates="zone", lazy="selectin"
    )
    schedules: Mapped[list["IrrigationSchedule"]] = relationship(  # noqa: F821
        back_populates="zone", lazy="selectin"
    )

    # ---------------- Later-phase extension points (no fake data) ---------
    # sprinkler_lines/valves (Module 8) — added in Phase 4 migration
