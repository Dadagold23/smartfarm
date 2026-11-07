"""Open-Meteo provider — REAL forecast API, no key required (HTTPS/JSON).

https://open-meteo.com/ free tier: daily min/max temperature, relative
humidity, wind speed, precipitation sum and precipitation probability for
up to 16 days. Units are converted to the ASIIS schema here (km/h -> m/s);
nothing is inferred beyond what the API returns, and `confidence` stays
None because Open-Meteo does not publish a per-day confidence value
(spec: no invented parameters presented as validated).

Requires farm coordinates (latitude/longitude set on /farms). Verified
against the live API (see README "Forecast providers" for the actual call
and response).
"""

from datetime import datetime
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.models.farm import Farm
from app.services.weather_providers.base import (
    ForecastDay,
    WeatherProvider,
    WeatherProviderError,
)

# Open-Meteo free tier caps at 16 forecast days.
MAX_DAYS = 16
_DAILY_FIELDS = ",".join([
    "temperature_2m_min", "temperature_2m_max", "relative_humidity_2m_mean",
    "wind_speed_10m_max", "precipitation_sum", "precipitation_probability_max",
])


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


class OpenMeteoProvider(WeatherProvider):
    provider_id = "open_meteo"
    is_simulated = False

    def fetch_forecast(self, farm: Farm, days: int,
                       issued_at: datetime) -> list[ForecastDay]:
        settings = get_settings()
        if farm.latitude is None or farm.longitude is None:
            raise WeatherProviderError(
                f"farm {farm.id} has no coordinates; set latitude/longitude "
                "before using a real forecast provider"
            )
        if not 1 <= days <= MAX_DAYS:
            raise WeatherProviderError(
                f"open_meteo supports 1..{MAX_DAYS} forecast days, got {days}")
        params = {
            "latitude": str(farm.latitude),
            "longitude": str(farm.longitude),
            "daily": _DAILY_FIELDS,
            "timezone": "GMT",          # ASIIS stores naive UTC everywhere
            "wind_speed_unit": "ms",
            "forecast_days": str(days),
        }
        url = f"{settings.OPEN_METEO_BASE_URL.rstrip('/')}/forecast"
        try:
            resp = httpx.get(url, params=params, timeout=settings.WEATHER_PROVIDER_TIMEOUT_S)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            raise WeatherProviderError(f"open-meteo request failed: {exc}") from None
        except ValueError as exc:
            raise WeatherProviderError(f"open-meteo returned non-JSON: {exc}") from None

        daily = body.get("daily") or {}
        times = daily.get("time") or []
        if not times:
            raise WeatherProviderError(
                f"open-meteo response missing daily forecast: {str(body)[:200]}")

        def col(name):
            return daily.get(name) or [None] * len(times)

        rows: list[ForecastDay] = []
        for i, day in enumerate(times):
            rows.append(ForecastDay(
                forecast_date=datetime.strptime(day, "%Y-%m-%d").date(),
                temp_min_c=_dec(col("temperature_2m_min")[i]),
                temp_max_c=_dec(col("temperature_2m_max")[i]),
                humidity_pct=_dec(col("relative_humidity_2m_mean")[i]),
                wind_speed_m_s=_dec(col("wind_speed_10m_max")[i]),
                precipitation_mm=_dec(col("precipitation_sum")[i]),
                rain_probability_pct=_dec(col("precipitation_probability_max")[i]),
                confidence=None,  # provider states none — never invent one
                raw={"time": day},
            ))
        return rows
