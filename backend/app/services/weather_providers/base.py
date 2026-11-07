"""Weather provider contract (Module 6)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.core.exceptions import AppError
from app.models.farm import Farm


class WeatherProviderError(AppError):
    """Provider misconfigured/unavailable or returned unusable data."""

    status_code = 502
    code = "weather_provider_error"


@dataclass(frozen=True)
class ForecastDay:
    """One day-granular forecast record (provider-normalised units).

    Every field is exactly what the PROVIDER stated; None means the
    provider did not report it (never filled with a made-up number).
    `confidence` must be the provider's own stated confidence — the
    simulator reports its declared placeholder value, real providers that
    do not publish confidence leave it None.
    """

    forecast_date: date
    temp_min_c: Decimal | None = None
    temp_max_c: Decimal | None = None
    humidity_pct: Decimal | None = None
    wind_speed_m_s: Decimal | None = None
    precipitation_mm: Decimal | None = None
    rain_probability_pct: Decimal | None = None
    confidence: Decimal | None = None
    raw: dict | None = None


class WeatherProvider(ABC):
    provider_id: str = ""
    #: True => everything it returns is simulated and MUST be flagged.
    is_simulated: bool = False
    #: True => needs an environment-provided API key (extension point).
    requires_api_key: bool = False

    def is_configured(self) -> bool:
        return not self.requires_api_key

    @abstractmethod
    def fetch_forecast(self, farm: Farm, days: int,
                       issued_at: datetime) -> list[ForecastDay]:
        """Return `days` day-granular records starting at issued_at.date().

        Implementations must not invent values for data the provider does
        not supply and must raise WeatherProviderError on failure — never
        silently fall back to fake rows on a real-provider path.
        """
