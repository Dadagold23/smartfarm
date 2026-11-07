"""Module 5 — Soil intelligence: probe reading time series (Phase 2 scope).

Soil *profiles* / texture / chemistry (the rest of Module 5) land with the
Phase 3 ET engine; this table is the measured-moisture foundation they
consume. Values are accepted only from device-authenticated telemetry, and
every row records whether it came from the spec-sanctioned simulator
(`is_simulated`) so downstream code and the UI can never present simulated
data as measured.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ReadingSource(str, enum.Enum):
    device = "device"        # HTTP telemetry endpoint
    mqtt = "mqtt"            # MQTT bus ingestion
    manual = "manual"        # reserved (no UI yet; kept honest)


class SoilReading(Base, TimestampMixin):
    """One probe report at one point in time.

    Dedupe rule (telemetry pipeline): (device_id, measured_at) is unique —
    a replayed payload is rejected as a conflict, not double-counted.
    `quality_flags` is a JSON list of flag codes (out_of_range, flatline,
    suspect_timestamp); flagged readings are STORED (evidence) but marked,
    and a DeviceFaultEvent is raised for the operator.
    """

    __tablename__ = "soil_readings"
    __table_args__ = (
        UniqueConstraint("device_id", "measured_at", name="uq_soil_device_measured"),
        # farm-scoped history/latest queries (GET /soil/history?farm_id=…)
        Index("ix_soil_readings_farm_measured", "farm_id", "measured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Denormalised for farm-scoped queries (device is immutable parent).
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("irrigation_zones.id", ondelete="SET NULL"), index=True, nullable=True
    )
    probe_depth_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)

    measured_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    moisture_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    ec_mS_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)

    quality_flags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[ReadingSource] = mapped_column(
        Enum(ReadingSource, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ReadingSource.device,
    )
    raw_payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    ingest_batch_id: Mapped[str] = mapped_column(String(36), default="", nullable=False)

    device: Mapped["Device"] = relationship(back_populates="soil_readings")  # noqa: F821
