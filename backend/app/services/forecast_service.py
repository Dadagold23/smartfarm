"""Phase 2 (Module 6) — forecast refresh write path.

The reserved slot in the ingestion layer, now live: provider adapter ->
`weather_forecasts` table -> existing GET /weather/forecasts read side.

Rules honoured here:
  * provenance is persisted per row (`provider`, `is_simulated`): the
    simulator writes provider='simulated', is_simulated=true so the UI can
    badge every placeholder day — the spec-sanctioned stand-in until the
    Phase 3 FAO data pipeline replaces it;
  * refresh is idempotent per (farm, provider, issued_at, forecast_date) —
    replays UPDATE the stored day rather than spamming duplicates;
  * the issued day itself (lead 0) plus the following `days - 1` days are
    written, `lead_time_days` computed on write;
  * every refresh is audited (`weather.forecast_refresh`).
"""

from datetime import datetime
import json

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.farm import Farm
from app.models.user import User
from app.models.weather import WeatherForecast
from app.services import audit_service, farm_service
from app.services.weather_providers import get_provider
from app.services.weather_providers.base import ForecastDay


def refresh_forecasts(
    db: Session, user: User, held: set[str], *, farm_id: int,
    days: int | None = None, provider_id: str | None = None,
    issued_at: datetime | None = None, ip_address: str = "",
) -> dict:
    """Pull one forecast issue from the selected provider and persist it.

    `issued_at` defaults to now (naive UTC); tests/crons may pin it for
    deterministic replays. Returns a summary plus the stored rows.
    """
    settings = get_settings()
    farm: Farm = farm_service.get_accessible_farm(db, farm_id, user, "read", held)
    provider = get_provider(provider_id or settings.WEATHER_PROVIDER)
    horizon = days or settings.WEATHER_FORECAST_DAYS
    if issued_at is None:
        from app.services.device_service import utcnow_naive
        issued_at = utcnow_naive().replace(second=0, microsecond=0)

    data: list[ForecastDay] = provider.fetch_forecast(farm, horizon, issued_at)

    created = updated = 0
    for day in data:
        lead = max((day.forecast_date - issued_at.date()).days, 0)
        row = (
            db.query(WeatherForecast)
            .filter(WeatherForecast.farm_id == farm.id,
                    WeatherForecast.provider == provider.provider_id,
                    WeatherForecast.issued_at == issued_at,
                    WeatherForecast.forecast_date == day.forecast_date)
            .first()
        )
        if row is None:
            row = WeatherForecast(
                farm_id=farm.id, provider=provider.provider_id,
                issued_at=issued_at, forecast_date=day.forecast_date,
            )
            db.add(row)
            created += 1
        else:
            updated += 1
        row.lead_time_days = lead
        row.temp_min_c = day.temp_min_c
        row.temp_max_c = day.temp_max_c
        row.humidity_pct = day.humidity_pct
        row.wind_speed_m_s = day.wind_speed_m_s
        row.precipitation_mm = day.precipitation_mm
        row.rain_probability_pct = day.rain_probability_pct
        row.confidence = day.confidence
        row.is_simulated = provider.is_simulated
        row.raw_payload = json.dumps(day.raw or {}, default=str)

    audit_service.log(
        db, user_id=user.id, actor_label=user.email,
        action="weather.forecast_refresh", resource_type="farm",
        resource_id=farm.id,
        details={"provider": provider.provider_id, "days": horizon,
                 "issued_at": issued_at, "created": created,
                 "updated": updated, "is_simulated": provider.is_simulated},
        ip_address=ip_address,
    )
    db.commit()

    rows = (
        db.query(WeatherForecast)
        .filter(WeatherForecast.farm_id == farm.id,
                WeatherForecast.provider == provider.provider_id,
                WeatherForecast.issued_at == issued_at)
        .order_by(WeatherForecast.forecast_date)
        .all()
    )
    return {
        "farm_id": farm.id,
        "provider": provider.provider_id,
        "is_simulated": provider.is_simulated,
        "issued_at": issued_at,
        "days": horizon,
        "created": created,
        "updated": updated,
        "items": rows,
    }
