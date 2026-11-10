"""Phase 2 schemas — device management, device-authenticated telemetry,
soil readings, fault events.

Two hard-boundary layers, by design:
  1. Pydantic HARD limits here reject values that are meaningless at any
     sensor (garbage protection, HTTP 422).
  2. `app.services.telemetry_service` PHYSICAL/OPERATING ranges flag
     implausible-but-formattable readings (out_of_range fault) while still
     storing them as evidence. Operating ranges are hardware spec limits
     (e.g. -40..85 °C sensor junction range), NOT invented agronomic
     thresholds.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.iot import DeviceCommandStatus, DeviceStatus, DeviceType, FaultType
from app.models.soil import ReadingSource

DEVICE_CODE_RE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$"


def _to_naive_utc(value: datetime) -> datetime:
    """Telemetry timestamps are stored naive-UTC (codebase convention)."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# ---------------------------------------------------------------------------
# Device management (user JWT side)
# ---------------------------------------------------------------------------

class DeviceCreate(BaseModel):
    farm_id: int
    zone_id: int | None = None
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=32, pattern=DEVICE_CODE_RE)
    device_type: DeviceType = DeviceType.soil_probe
    model: str = Field(default="", max_length=120)
    firmware_version: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def _controller_requires_zone(self) -> "DeviceCreate":
        if self.device_type == DeviceType.irrigation_controller and self.zone_id is None:
            raise ValueError("irrigation controllers must be assigned to a zone")
        return self


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    zone_id: int | None = None
    model: str | None = Field(default=None, max_length=120)
    firmware_version: str | None = Field(default=None, max_length=64)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    zone_id: int | None
    name: str
    code: str
    device_type: DeviceType
    status: DeviceStatus
    key_prefix: str
    key_issued_at: datetime | None
    model: str
    firmware_version: str
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeviceRegisterOut(BaseModel):
    """Shown ONCE: the only API response that ever carries the plaintext key."""

    device: DeviceOut
    api_key: str
    notice: str = (
        "Store this device key now — it cannot be retrieved later. "
        "Rotate it if lost; the old key stops working immediately."
    )


class FaultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    farm_id: int
    fault_type: FaultType
    message: str
    details_json: str
    detected_at: datetime
    resolved_at: datetime | None


class DeviceStatusOut(BaseModel):
    """Computed liveness view (staleness is derived, never stored)."""

    device: DeviceOut
    last_seen_minutes_ago: int | None
    is_stale: bool
    open_faults: list[FaultOut] = []


class DeviceCommandAck(BaseModel):
    status: Literal["acked", "failed"] = "acked"
    message: str | None = Field(default=None, max_length=500)
    observed_running: bool | None = None
    interlocks_clear: bool | None = None
    flow_lpm: Decimal | None = Field(default=None, ge=0, le=2000)
    pressure_bar: Decimal | None = Field(default=None, ge=0, le=100)


class DeviceCommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    farm_id: int
    zone_id: int | None
    control_action: str | None
    command: str
    payload_json: str
    status: DeviceCommandStatus
    attempts: int
    sent_at: datetime | None
    acked_at: datetime | None
    ack_message: str | None
    correlation_id: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeviceCommandListOut(BaseModel):
    items: list[DeviceCommandOut]


class DeviceHeartbeatOut(BaseModel):
    ok: bool
    last_seen_at: datetime


class ControllerRuntimeIn(BaseModel):
    zone_id: int
    start_command_id: int
    is_running: bool
    completed: bool = False
    flow_lpm: Decimal | None = Field(default=None, ge=0, le=2000)
    pressure_bar: Decimal | None = Field(default=None, ge=0, le=100)
    delivered_volume_m3: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _completion_requires_stopped_state(self) -> "ControllerRuntimeIn":
        if self.completed and self.is_running:
            raise ValueError("completed runtime report must indicate the zone is stopped")
        return self


# ---------------------------------------------------------------------------
# Telemetry ingestion (device key side; NOT user JWT)
# ---------------------------------------------------------------------------

class SoilTelemetryIn(BaseModel):
    measured_at: datetime
    moisture_pct: Decimal | None = Field(default=None, ge=-50, le=150)
    temperature_c: Decimal | None = Field(default=None, ge=-100, le=150)
    ec_mS_cm: Decimal | None = Field(default=None, ge=-1, le=100)
    probe_depth_cm: Decimal | None = Field(default=None, gt=0, le=300)
    simulated: bool = Field(
        default=False,
        description="Set by the spec-sanctioned sensor simulator; real "
        "hardware never sends it. Persisted as is_simulated and badged in the UI.",
    )

    @field_validator("measured_at")
    @classmethod
    def _naive(cls, v: datetime) -> datetime:
        return _to_naive_utc(v)

    @model_validator(mode="after")
    def _at_least_one_metric(self) -> "SoilTelemetryIn":
        if self.moisture_pct is None and self.temperature_c is None and self.ec_mS_cm is None:
            raise ValueError("soil telemetry must carry at least one metric")
        return self


class WeatherTelemetryIn(BaseModel):
    measured_at: datetime
    temperature_c: Decimal | None = Field(default=None, ge=-100, le=150)
    humidity_pct: Decimal | None = Field(default=None, ge=-50, le=150)
    wind_speed_m_s: Decimal | None = Field(default=None, ge=0, le=200)
    wind_direction_deg: Decimal | None = Field(default=None, ge=0, le=360)
    solar_radiation_w_m2: Decimal | None = Field(default=None, ge=0, le=2000)
    rainfall_mm: Decimal | None = Field(default=None, ge=-5, le=2000)
    pressure_hpa: Decimal | None = Field(default=None, ge=100, le=2000)
    simulated: bool = Field(default=False, description="See SoilTelemetryIn.simulated.")

    @field_validator("measured_at")
    @classmethod
    def _naive(cls, v: datetime) -> datetime:
        return _to_naive_utc(v)

    @model_validator(mode="after")
    def _at_least_one_metric(self) -> "WeatherTelemetryIn":
        metrics = [
            self.temperature_c, self.humidity_pct, self.wind_speed_m_s,
            self.solar_radiation_w_m2, self.rainfall_mm, self.pressure_hpa,
        ]
        if all(m is None for m in metrics):
            raise ValueError("weather telemetry must carry at least one metric")
        return self


class TelemetryIngestResult(BaseModel):
    """Result envelope returned by the shared ingest pipeline (HTTP+MQTT)."""

    ok: bool
    status: str = Field(
        description="'accepted' | 'duplicate' (idempotent replay) | "
        "'rejected' (bad timestamp / no metric)."
    )
    reading_id: int | None = None
    measured_at: datetime | None = None
    quality_flags: list[str] = []
    is_simulated: bool = False
    error: str | None = None
    faults: list[FaultOut] = []


class TelemetryBatchMeta(BaseModel):
    """Per-item outcomes for a batch POST; `batch_id` ties stored readings."""

    device_id: int
    batch_id: str
    accepted: int
    duplicates: int
    rejected: int
    results: list[TelemetryIngestResult]


class SoilTelemetryBatchIn(BaseModel):
    """Body of POST /telemetry/soil.

    `device_id` is only consulted on the user-JWT path (an admin/manager
    uploading on behalf of a device); the device-key path is implicitly
    bound to its own device and must NOT set it.
    """

    device_id: int | None = None
    readings: list[SoilTelemetryIn] = Field(min_length=1)


class WeatherTelemetryBatchIn(BaseModel):
    device_id: int | None = None
    readings: list[WeatherTelemetryIn] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Soil readings (user JWT read side)
# ---------------------------------------------------------------------------

class SoilReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    farm_id: int
    zone_id: int | None
    probe_depth_cm: Decimal | None
    measured_at: datetime
    received_at: datetime
    moisture_pct: Decimal | None
    temperature_c: Decimal | None
    ec_mS_cm: Decimal | None
    quality_flags: list[str]
    is_simulated: bool
    source: ReadingSource

    @field_validator("quality_flags", mode="before")
    @classmethod
    def _parse_flags(cls, v):
        # Stored as a JSON array string; served as a real list so the UI
        # can badge each reading without re-parsing.
        if isinstance(v, str):
            import json
            try:
                return json.loads(v or "[]")
            except ValueError:
                return []
        return v
