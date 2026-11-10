"""Farm and irrigation-zone schemas (Module 2)."""

from datetime import datetime
from decimal import Decimal

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.farm import FarmStatus, WaterSourceType, ZoneControlMode, ZoneStatus

CODE_RE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$"


class GeometryMixin(BaseModel):
    geometry: str | None = Field(
        default=None, description="Optional GeoJSON (Polygon/Point) text"
    )

    @field_validator("geometry")
    @classmethod
    def _geometry_must_parse_as_json(cls, v: str | None) -> str | None:
        # Validation at the schema boundary: reject garbage GeoJSON early.
        if v is not None:
            import json

            try:
                parsed = json.loads(v)
            except (TypeError, ValueError) as exc:
                raise ValueError("geometry must be valid JSON (GeoJSON)") from exc
            if not isinstance(parsed, dict) or "type" not in parsed:
                raise ValueError("geometry must be a GeoJSON object with a 'type'")
        return v


class FarmBase(GeometryMixin):
    name: str = Field(min_length=2, max_length=255)
    code: str = Field(min_length=1, max_length=32, pattern=CODE_RE)
    description: str = Field(default="", max_length=4000)
    country: str = Field(default="", max_length=120)
    region: str = Field(default="", max_length=120)
    locality: str = Field(default="", max_length=255)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    elevation_m: Decimal | None = Field(default=None, ge=-430, le=8850)
    area_ha: Decimal | None = Field(default=None, gt=0)
    water_source: WaterSourceType = WaterSourceType.other
    status: FarmStatus = FarmStatus.active


class FarmCreate(FarmBase):
    owner_id: int | None = Field(
        default=None,
        description="Admin-only: create the farm for another user.",
    )


class FarmUpdate(GeometryMixin):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=32, pattern=CODE_RE)
    description: str | None = Field(default=None, max_length=4000)
    country: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    locality: str | None = Field(default=None, max_length=255)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    elevation_m: Decimal | None = Field(default=None, ge=-430, le=8850)
    area_ha: Decimal | None = Field(default=None, gt=0)
    water_source: WaterSourceType | None = None
    status: FarmStatus | None = None


class ZoneBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    status: ZoneStatus


class FarmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    name: str
    code: str
    description: str
    country: str
    region: str
    locality: str
    latitude: Decimal | None
    longitude: Decimal | None
    elevation_m: Decimal | None
    geometry: str | None
    area_ha: Decimal | None
    water_source: WaterSourceType
    status: FarmStatus
    created_at: datetime
    updated_at: datetime
    zones: list[ZoneBrief] = []


class ZoneBase(GeometryMixin):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=32, pattern=CODE_RE)
    area_ha: Decimal | None = Field(default=None, gt=0)
    sequence_number: int = Field(default=0, ge=0)
    status: ZoneStatus = ZoneStatus.active
    control_mode: ZoneControlMode = ZoneControlMode.automatic
    max_application_mm_per_hour: Decimal | None = Field(default=None, gt=0, le=500)


class ZoneCreate(ZoneBase):
    pass


class ZoneUpdate(GeometryMixin):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=32, pattern=CODE_RE)
    area_ha: Decimal | None = Field(default=None, gt=0)
    sequence_number: int | None = Field(default=None, ge=0)
    status: ZoneStatus | None = None
    max_application_mm_per_hour: Decimal | None = Field(default=None, gt=0, le=500)


class ZoneControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["start", "stop", "emergency_stop", "clear_emergency_stop"]
    control_mode: ZoneControlMode | None = None
    schedule_id: int | None = Field(default=None, gt=0)


class ZoneOut(ZoneBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    is_running: bool
    emergency_stop: bool
    current_flow_lpm: Decimal | None
    pressure_bar: Decimal | None
    last_started_at: datetime | None
    last_stopped_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ZoneControlOut(ZoneOut):
    command_id: int | None = None
    command_status: str | None = None
    control_message: str | None = None
