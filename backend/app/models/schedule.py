"""Module 7 — Intelligent Irrigation Scheduling Engine.

Stores calculated FAO-56 Penman-Monteith reference evapotranspiration (ET0),
crop evapotranspiration (ETc), root-zone soil water depletion (Dr), and
scientifically determined irrigation durations and volumes per agricultural zone.
Full equation inputs are saved for complete auditability.
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ScheduleStatus(str, enum.Enum):
    recommended = "recommended"
    approved = "approved"
    rejected = "rejected"
    executing = "executing"
    completed = "completed"
    cancelled = "cancelled"
    skipped_weather = "skipped_weather"


class ScheduleReason(str, enum.Enum):
    depletion_threshold_exceeded = "depletion_threshold_exceeded"
    soil_sensor_trigger = "soil_sensor_trigger"
    scheduled_interval = "scheduled_interval"
    manual_request = "manual_request"
    weather_forecast_mitigation = "weather_forecast_mitigation"


class IrrigationSchedule(Base, TimestampMixin):
    """Calculated irrigation schedule and scientific water balance record."""

    __tablename__ = "irrigation_schedules"
    __table_args__ = (
        Index("ix_schedules_farm_target", "farm_id", "target_date"),
        Index("ix_schedules_zone_target", "zone_id", "target_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_id: Mapped[int] = mapped_column(
        ForeignKey("irrigation_zones.id", ondelete="CASCADE"), index=True, nullable=False
    )
    planting_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("planting_batches.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    calculation_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Scientific FAO-56 components (mm/day)
    reference_et0_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    crop_kc: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    crop_etc_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)

    # Precipitation and balance terms (mm)
    forecast_precipitation_mm: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), default=Decimal("0.0"), nullable=False
    )
    effective_precipitation_mm: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), default=Decimal("0.0"), nullable=False
    )

    # Soil moisture & root-zone parameters
    current_soil_moisture_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    root_depth_m: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    total_available_water_mm: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    readily_available_water_mm: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    root_zone_depletion_mm: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    water_stress_coefficient_ks: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), default=Decimal("1.0"), nullable=False
    )

    # Net and Gross irrigation requirements
    net_irrigation_requirement_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    application_efficiency_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("85.0"), nullable=False
    )
    gross_irrigation_requirement_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)

    # Operational execution parameters
    recommended_runtime_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_volume_m3: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    status: Mapped[ScheduleStatus] = mapped_column(
        Enum(ScheduleStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ScheduleStatus.recommended,
    )
    reason: Mapped[ScheduleReason] = mapped_column(
        Enum(ScheduleReason, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ScheduleReason.depletion_threshold_exceeded,
    )

    recommended_start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recommended_end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Interlock flags
    safety_checks_passed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    weather_skip_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Full audit record of calculation inputs and intermediate equations
    calculation_metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    # Relationships
    farm: Mapped["Farm"] = relationship(back_populates="schedules")  # noqa: F821
    zone: Mapped["IrrigationZone"] = relationship(back_populates="schedules")  # noqa: F821
    planting_batch: Mapped["PlantingBatch | None"] = relationship(back_populates="schedules")  # noqa: F821
