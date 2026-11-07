"""Module 6 — Weather intelligence (Phase 2 scope).

Two distinct data kinds, deliberately separate tables:

* `WeatherObservation` — *measured* conditions reported by registered
  weather stations through the same device-authenticated telemetry
  pipeline as soil probes.
* `WeatherForecast` — *provider-sourced* day-granular predictions from a
  weather provider adapter (see app/services/weather_providers). Each row
  stores its provider, issue time, lead time and confidence, and an
  `is_simulated` flag: simulator-produced forecasts are labelled as
  simulated in the DB and in every API response, so they can never be
  mistaken for real forecast science (spec: no invented parameters).
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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ObservationSource(str, enum.Enum):
    device = "device"
    mqtt = "mqtt"
    manual = "manual"  # reserved (no UI yet; kept honest)


class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    __table_args__ = (
        UniqueConstraint("device_id", "measured_at", name="uq_wxobs_device_measured"),
        # farm-scoped history/latest queries (GET /weather/history?farm_id=…)
        Index("ix_wxobs_farm_measured", "farm_id", "measured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )

    measured_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    humidity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    wind_speed_m_s: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    wind_direction_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    solar_radiation_w_m2: Mapped[Decimal | None] = mapped_column(Numeric(7, 1), nullable=True)
    rainfall_mm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    pressure_hpa: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)

    quality_flags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[ObservationSource] = mapped_column(
        Enum(ObservationSource, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ObservationSource.device,
    )
    raw_payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    ingest_batch_id: Mapped[str] = mapped_column(String(36), default="", nullable=False)

    device: Mapped["Device"] = relationship(back_populates="weather_observations")  # noqa: F821


class WeatherForecast(Base):
    """Day-granular provider forecast for one farm.

    `lead_time_days` = forecast_date - issued_at (computed on write);
    `confidence` is only ever populated with the PROVIDER's own stated
    confidence (or, for the simulator, its declared model confidence) —
    never an invented number presented as real science.
    """

    __tablename__ = "weather_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "farm_id", "provider", "issued_at", "forecast_date",
            name="uq_forecast_farm_provider_issue_day",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id", ondelete="CASCADE"), index=True, nullable=False
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    temp_min_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    temp_max_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    precipitation_mm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    rain_probability_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    wind_speed_m_s: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    humidity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
