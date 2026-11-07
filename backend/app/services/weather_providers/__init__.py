"""Phase 2 (Module 6) — weather provider adapters.

Contract (`base.WeatherProvider`): given a farm, a horizon in days and an
issue timestamp, return day-granular forecast rows. The service layer
(`app.services.forecast_service`) persists them into `weather_forecasts`
through the reserved `ForecastRefreshIn` write path; nothing is faked at
read time — GET /weather/forecasts only ever returns stored provider rows.

Registry:
  * `simulated`   — offline deterministic provider (spec-sanctioned
                    simulator for development without external services).
                    Every row it writes carries provider='simulated' and
                    is_simulated=true; it is a PLACEHOLDER for Phase 3's
                    FAO-data pipeline, NOT validated forecast science.
  * `open_meteo`  — real public forecast API (no key required) via HTTPS.
  * `open_weather_map` — >>> EXTENSION POINT <<< real key-licensed API;
                    reads OPEN_WEATHER_MAP_API_KEY from the environment
                    (never from code). Without a key it refuses to serve
                    instead of pretending.

Adding a provider: implement WeatherProvider in a module here and add it
to `_REGISTRY` below; config WEATHER_PROVIDER selects the default by id.
"""

from app.services.weather_providers.base import (
    ForecastDay,
    WeatherProvider,
    WeatherProviderError,
)
from app.services.weather_providers.open_meteo import OpenMeteoProvider
from app.services.weather_providers.open_weather_map import (
    OpenWeatherMapProvider,
)
from app.services.weather_providers.simulator import SimulatorProvider

_SIMULATOR_ID = "simulated"

_REGISTRY: dict[str, WeatherProvider] = {
    _SIMULATOR_ID: SimulatorProvider(),
    "open_meteo": OpenMeteoProvider(),
    "open_weather_map": OpenWeatherMapProvider(),
}


def get_provider(provider_id: str | None) -> WeatherProvider:
    key = (provider_id or "").strip() or _SIMULATOR_ID
    provider = _REGISTRY.get(key)
    if provider is None:
        raise WeatherProviderError(
            f"unknown weather provider {key!r}; available: "
            f"{', '.join(sorted(_REGISTRY))}"
        )
    return provider


def available_providers() -> list[dict]:
    return [
        {
            "id": p.provider_id,
            "is_simulated": p.is_simulated,
            "requires_api_key": p.requires_api_key,
            "configured": p.is_configured(),
        }
        for p in _REGISTRY.values()
    ]
