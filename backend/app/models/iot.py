"""Module 9 (Phase 2 core) — IoT device registry + sensor failure events.

Device authentication model (docs/ARCHITECTURE.md §8):
  * Each device gets a high-entropy API key at registration. The plaintext
    key is returned ONCE (never stored); the DB keeps its SHA-256 digest.
    Keys are random 256-bit tokens, so a fast salted hash is not needed —
    the digest plus constant-time comparison is the standard scheme for
    machine credentials (user passwords keep using bcrypt).
  * Telemetry ingestion (HTTP or MQTT) authenticates with that key, never
    with a user JWT. Rotating or revoking a key takes effect immediately.

Timestamps: `last_seen_at` is naive UTC, matching the rest of the codebase.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class DeviceType(str, enum.Enum):
    soil_probe = "soil_probe"
    weather_station = "weather_station"
    combined_station = "combined_station"
    gateway = "gateway"
    irrigation_controller = "irrigation_controller"
    other = "other"  # spec: "other" device class (valves etc. arrive Phase 4)


class DeviceStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"


class DeviceCommandStatus(str, enum.Enum):
    queued = "queued"
    sent = "sent"
    acked = "acked"
    failed = "failed"
    expired = "expired"
    cancelled = "cancelled"


class FaultType(str, enum.Enum):
    stale_data = "stale_data"          # no accepted reading beyond threshold
    out_of_range = "out_of_range"      # physically implausible value
    flatline = "flatline"              # N consecutive identical values
    auth_failure = "auth_failure"      # rejected/unexpected device credential


DEVICE_CODE_RE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$"


class Device(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("farm_id", "code", name="uq_devices_farm_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("irrigation_zones.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    device_type: Mapped[DeviceType] = mapped_column(
        Enum(DeviceType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=DeviceType.soil_probe,
    )
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=DeviceStatus.active,
    )

    # Machine credential. `key_hash` = sha256 hex of the device API key;
    # `key_prefix` = first 8 chars of the plaintext, for UI identification
    # only (never used for authentication).
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    key_issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    firmware_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # ESP32-style devices send local (possibly skewed) timestamps; the
    # gateway-reported UTC arrival time is stored per reading instead.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    farm: Mapped["Farm"] = relationship(back_populates="devices")  # noqa: F821
    zone: Mapped[Optional["IrrigationZone"]] = relationship(back_populates="devices")  # noqa: F821

    soil_readings: Mapped[list["SoilReading"]] = relationship(  # noqa: F821
        back_populates="device", cascade="all, delete-orphan", lazy="selectin"
    )
    weather_observations: Mapped[list["WeatherObservation"]] = relationship(  # noqa: F821
        back_populates="device", cascade="all, delete-orphan", lazy="selectin"
    )
    fault_events: Mapped[list["DeviceFaultEvent"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", lazy="selectin"
    )
    commands: Mapped[list["DeviceCommand"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", lazy="selectin"
    )

    # ---------------- Phase 4 extension points (no fake data) -------------
    # valve controllers / command channel downlink (Module 8/9 safety envelope)


class DeviceCommand(Base, TimestampMixin):
    __tablename__ = "device_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("irrigation_zones.id", ondelete="CASCADE"), index=True, nullable=True
    )
    control_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    command: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[DeviceCommandStatus] = mapped_column(
        Enum(DeviceCommandStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=DeviceCommandStatus.queued,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ack_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device: Mapped[Device] = relationship(back_populates="commands")
    zone: Mapped[Optional["IrrigationZone"]] = relationship()  # noqa: F821


class DeviceFaultEvent(Base, TimestampMixin):
    """Sensor failure detection output (spec: "Sensor failure detection").

    One open event per (device, fault_type): services reopen/refresh rather
    than spam duplicates; resolution sets `resolved_at`. Events are surfaced
    through the API (device status, fault list) and mirrored to the audit
    log; they are never hard-deleted by application code.
    """

    __tablename__ = "device_fault_events"
    __table_args__ = (
        UniqueConstraint("device_id", "fault_type", "open_marker",
                         name="uq_fault_open_per_device_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Denormalised for cheap farm-scoped queries (kept in sync by services).
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    fault_type: Mapped[FaultType] = mapped_column(
        Enum(FaultType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Integrity trick for "at most one OPEN event per (device, type)":
    # open rows carry open_marker=1 (unique-constrained), resolved rows
    # carry NULL (SQLite/Postgres allow unlimited NULLs in unique indexes).
    open_marker: Mapped[int | None] = mapped_column(nullable=True, default=None)

    device: Mapped[Device] = relationship(back_populates="fault_events")
