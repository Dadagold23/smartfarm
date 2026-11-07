"""Module 6 schemas — weather observations, provider forecasts, refresh."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.weather import ObservationSource


class WeatherObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    farm_id: int
    measured_at: datetime
    received_at: datetime
    temperature_c: Decimal | None
    humidity_pct: Decimal | None
    wind_speed_m_s: Decimal | None
    wind_direction_deg: Decimal | None
    solar_radiation_w_m2: Decimal | None
    rainfall_mm: Decimal | None
    pressure_hpa: Decimal | None
    quality_flags: list[str]
    is_simulated: bool
    source: ObservationSource

    @field_validator("quality_flags", mode="before")
    @classmethod
    def _parse_flags(cls, v):
        # Stored as a JSON array string; served as a real list so the UI
        # can badge each observation without re-parsing.
        if isinstance(v, str):
            import json
            try:
                return json.loads(v or "[]")
            except ValueError:
                return []
        return v


class WeatherForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    farm_id: int
    provider: str
    issued_at: datetime
    forecast_date: date
    lead_time_days: int
    temp_min_c: Decimal | None
    temp_max_c: Decimal | None
    precipitation_mm: Decimal | None
    rain_probability_pct: Decimal | None
    wind_speed_m_s: Decimal | None
    humidity_pct: Decimal | None
    confidence: Decimal | None
    is_simulated: bool
    created_at: datetime


class ForecastRefreshIn(BaseModel):
    farm_id: int
    days: int = Field(default=7, ge=1, le=16)
    provider: str | None = Field(
        default=None,
        description="Provider id override; default = WEATHER_PROVIDER setting. "
        "Available: 'simulated' | 'open_meteo' | 'open_weather_map' "
        "(see GET /weather/forecast-providers).",
    )


class ForecastRefreshOut(BaseModel):
    """Outcome of one provider issue written to weather_forecasts."""

    farm_id: int
    provider: str
    is_simulated: bool
    issued_at: datetime
    days: int
    created: int
    updated: int
    items: list[WeatherForecastOut]


class WeatherProviderOut(BaseModel):
    """Registry entry metadata so the UI can offer provider choices honestly
    (which are simulated, which need a key, which are configured)."""

    id: str
    is_simulated: bool
    requires_api_key: bool
    configured: bool
