"""Module 6 — weather telemetry read endpoints (weather.read, farm-scoped).

Provenance flags are returned on every row: `is_simulated` on measured
observations, and `provider` + `is_simulated` on forecasts, so the UI can
badge simulated data instead of presenting it as measured/validated.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.schemas.weather import (
    ForecastRefreshIn,
    ForecastRefreshOut,
    WeatherForecastOut,
    WeatherObservationOut,
    WeatherProviderOut,
)
from app.services import forecast_service, telemetry_service
from app.services.weather_providers import available_providers

router = APIRouter()

RequiresWeatherRead = Annotated[set[str], Depends(require_permissions("weather.read"))]


@router.get("/latest", response_model=dict)
def weather_latest(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresWeatherRead,
    farm_id: int | None = None,
):
    items = telemetry_service.list_weather_latest(db, current_user, held, farm_id)
    return {"items": [WeatherObservationOut.model_validate(r) for r in items]}


@router.get("/history", response_model=dict)
def weather_history(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresWeatherRead,
    farm_id: int | None = None,
    device_id: int | None = None,
    start: datetime | None = Query(default=None, description="naive UTC"),
    end: datetime | None = Query(default=None, description="naive UTC"),
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: int = Query(0, ge=0),
):
    items, total = telemetry_service.list_weather_history(
        db, current_user, held, farm_id=farm_id, device_id=device_id,
        start=start, end=end, limit=limit, offset=offset,
    )
    return {
        "items": [WeatherObservationOut.model_validate(r).model_dump(mode="json")
                  for r in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.get("/forecasts", response_model=dict)
def weather_forecasts(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresWeatherRead,
    farm_id: int | None = None,
    days: Annotated[int | None, Query(ge=1, le=16)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: int = Query(0, ge=0),
):
    """Persisted provider forecasts (latest issue per farm). Rows only ever
    exist because POST /weather/forecast-refresh wrote them through a real
    provider adapter — this endpoint never synthesises values."""
    items, total = telemetry_service.list_forecasts(
        db, current_user, held, farm_id=farm_id, days=days,
        limit=limit, offset=offset,
    )
    return {
        "items": [WeatherForecastOut.model_validate(f).model_dump(mode="json")
                  for f in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.get("/forecast-providers", response_model=dict)
def forecast_providers(
    current_user: CurrentUser,
    held: RequiresWeatherRead,
):
    """Provider registry with honest capability metadata (simulated flag,
    key requirement, configuration state) for the UI's refresh control."""
    return {"items": [WeatherProviderOut.model_validate(p).model_dump(mode="json")
                      for p in available_providers()]}


@router.post("/forecast-refresh", response_model=ForecastRefreshOut)
def forecast_refresh(
    body: ForecastRefreshIn,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresWeatherRead,
):
    """Pull a fresh forecast issue from the selected provider and write it
    to weather_forecasts (audited, idempotent per issue).

    Default provider is the WEATHER_PROVIDER setting; 'simulated' rows are
    persisted with provider='simulated' + is_simulated=true so the UI can
    never badge them as real forecast science. Real providers raise a
    502 weather_provider_error when unreachable/unconfigured — they never
    fall back to fake data silently.
    """
    result = forecast_service.refresh_forecasts(
        db, current_user, held,
        farm_id=body.farm_id, days=body.days, provider_id=body.provider,
        ip_address=client_ip(request),
    )
    return ForecastRefreshOut.model_validate(result)
