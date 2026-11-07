"""OpenWeatherMap provider — KEY-LICENSED REAL API EXTENSION POINT.

This is the module the config block in app/core/config.py points at:
put the One Call 3.0 key in the environment (`OPEN_WEATHER_MAP_API_KEY`)
and select `WEATHER_PROVIDER=open_weather_map`; nothing else changes.

Honesty status (spec rule: no fabricated verification): the request/parse
code below is written against the documented One Call 3.0 response shape,
but NO API key exists in this development environment, so this adapter
has NOT been exercised against the live service. Until someone with a key
runs it (or uses `open_meteo`, which was live-verified), the default and
test path is the labeled `simulated` provider. If the live shape differs,
this module — and only this module — is where the fix lands.

Without a key the provider refuses loudly (WeatherProviderError); it never
falls back to fake rows on the real-provider path.
"""

from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.models.farm import Farm
from app.services.weather_providers.base import (
    ForecastDay,
    WeatherProvider,
    WeatherProviderError,
)

MAX_DAYS = 8  # One Call 3.0 daily horizon


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


class OpenWeatherMapProvider(WeatherProvider):
    provider_id = "open_weather_map"
    is_simulated = False
    requires_api_key = True

    def is_configured(self) -> bool:
        return bool(get_settings().OPEN_WEATHER_MAP_API_KEY.strip())

    def fetch_forecast(self, farm: Farm, days: int,
                       issued_at: datetime) -> list[ForecastDay]:
        settings = get_settings()
        key = settings.OPEN_WEATHER_MAP_API_KEY.strip()
        if not key:
            raise WeatherProviderError(
                "open_weather_map requires OPEN_WEATHER_MAP_API_KEY in the "
                "environment (extension point); choose provider='simulated' "
                "or 'open_meteo' until a key is configured"
            )
        if farm.latitude is None or farm.longitude is None:
            raise WeatherProviderError(
                f"farm {farm.id} has no coordinates; set latitude/longitude "
                "before using a real forecast provider"
            )
        if not 1 <= days <= MAX_DAYS:
            raise WeatherProviderError(
                f"open_weather_map supports 1..{MAX_DAYS} forecast days, got {days}")
        url = f"{settings.OPEN_WEATHER_MAP_BASE_URL.rstrip('/')}/onecall"
        params = {
            "lat": str(farm.latitude), "lon": str(farm.longitude),
            "exclude": "minutely,hourly,alerts",
            "units": "metric", "appid": key, "cnt": str(days),
        }
        try:
            resp = httpx.get(url, params=params,
                             timeout=settings.WEATHER_PROVIDER_TIMEOUT_S)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            raise WeatherProviderError(f"openweathermap request failed: {exc}") from None
        except ValueError as exc:
            raise WeatherProviderError(
                f"openweathermap returned non-JSON: {exc}") from None

        rows: list[ForecastDay] = []
        for day in body.get("daily") or []:
            # dt is UTC epoch seconds; ASIIS stores naive UTC.
            fdate = datetime.fromtimestamp(day["dt"], tz=timezone.utc).date()
            temp = day.get("temp") or {}
            pop = day.get("pop")
            # snow is reported as liquid-water-equivalent mm — summed, documented.
            has_precip = "rain" in day or "snow" in day
            precip = (day.get("rain") or 0.0) + (day.get("snow") or 0.0)
            rows.append(ForecastDay(
                forecast_date=fdate,
                temp_min_c=_dec(temp.get("min")),
                temp_max_c=_dec(temp.get("max")),
                humidity_pct=_dec(day.get("humidity")),
                wind_speed_m_s=_dec(day.get("wind_speed")),
                precipitation_mm=_dec(precip) if has_precip else None,
                rain_probability_pct=None if pop is None else _dec(pop * 100.0),
                confidence=None,  # OWM publishes no per-day confidence
                raw={"dt": day.get("dt")},
            ))
        if not rows:
            raise WeatherProviderError(
                "openweathermap returned no daily forecast rows")
        return rows
