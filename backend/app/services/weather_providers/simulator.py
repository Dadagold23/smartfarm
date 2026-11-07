"""Offline deterministic weather provider — spec-sanctioned SIMULATOR.

WHY THIS EXISTS: forecast data feeds irrigation recommendations (acceptance
req. 6), but development runs without an API key or internet. This provider
produces *day-granular placeholder* forecasts so the whole write/read path
(provider -> weather_forecasts -> GET /weather/forecasts) is real and
testable. It is explicitly the placeholder until Phase 3 wires validated
FAO/openscientific data (ET0 pipelines, station climatologies).

WHAT IT IS NOT: it contains **no agricultural or meteorological science**
and must never be presented as forecast skill. Values come from a
deterministic hash-seeded generator (pure function, no clock, no RNG
global state) bounded by physically plausible instrument limits (the same
sanity bounds the fault engine uses: temperature inside -40..85 °C,
humidity 0..100 %, rainfall >= 0). Any "structure" in the output (a
per-farm-year mean offset, humidity/rain coupling) is generator flavour
documented in `simulate_day`, deliberately NOT a seasonal or weather
model. Nothing here models real weather.

Determinism: identical (farm_id, issued date, forecast_date) => identical
values — across processes, machines and runs. This makes it usable from
tests and from the sensor simulator script with reproducible output.
"""

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.models.farm import Farm
from app.services.weather_providers.base import ForecastDay, WeatherProvider

# Declared placeholder confidence: the simulator states plainly that it is
# not a skillful model (0.0 <= c <= 1, shown in the API like any provider's
# confidence field). Real providers report their own or leave it None.
SIMULATOR_CONFIDENCE = Decimal("0.100")


def _unit01(*parts) -> float:
    """Deterministic pseudo-random float in [0, 1) from hashable parts.

    Pure function of the inputs (SHA-256); no global RNG state, so two
    processes agree bit-for-bit.
    """
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _quant(x: float, places: str = "0.01") -> Decimal:
    return Decimal(str(round(x, 2))).quantize(Decimal(places))


def simulate_day(farm_id: int, issued_on: date, forecast_date: date) -> ForecastDay:
    """One farm-day of placeholder forecast (pure function).

    Structure (documented, NOT scientific):
      * per-(farm, year) mean offset and per-day temperature anomaly from
        the hash seed — exists only so successive days look coherent in
        the UI;
      * diurnal range 5..15 °C; humidity anti-correlated with the day's
        temperature anomaly; rainfall as a Bernoulli-ish event with a
        stated probability, amount drawn when the event fires.
    All outputs are clamped inside physically instrument-plausible bounds.
    """
    seed = ("asiis-wx-sim", farm_id, issued_on.isoformat(), forecast_date.isoformat())
    lead = max((forecast_date - issued_on).days, 0)

    mean_c = 24.0 + 4.0 * (_unit01(*seed[:2], "year-shape", forecast_date.year) - 0.5) * 2.0
    anomaly = (_unit01(*seed, "anomaly") - 0.5) * 10.0
    t_max = mean_c + 5.0 + anomaly * 0.6
    t_min = t_max - (5.0 + _unit01(*seed, "range") * 10.0)
    t_max = max(-39.0, min(84.0, t_max))
    t_min = max(-40.0, min(t_max - 0.5, t_min))

    humidity = 35.0 + (t_max - (mean_c + 5.0)) * -2.5 \
        + _unit01(*seed, "hum") * 30.0
    humidity = max(5.0, min(100.0, humidity))

    wind = 0.5 + _unit01(*seed, "wind") * 9.0 + lead * 0.15  # less skill further out -> wider spread, still placeholder
    wind = min(wind, 40.0)

    rain_p = _unit01(*seed, "rainp") * 100.0
    # crude coherence: high humidity days more likely "wet" (documented
    # generator coupling, not a weather model)
    rain_p = max(0.0, min(100.0, rain_p * (0.4 + humidity / 166.7)))
    rain_mm = 0.0
    if _unit01(*seed, "raindraw") * 100.0 < rain_p:
        rain_mm = round(_unit01(*seed, "rainamt") ** 2 * 40.0, 1)

    return ForecastDay(
        forecast_date=forecast_date,
        temp_min_c=_quant(t_min),
        temp_max_c=_quant(t_max),
        humidity_pct=_quant(humidity),
        wind_speed_m_s=_quant(wind),
        precipitation_mm=_quant(rain_mm),
        rain_probability_pct=_quant(rain_p),
        confidence=SIMULATOR_CONFIDENCE,
        raw={"generator": "asiis-wx-sim/v1", "farm_id": farm_id,
             "issued_on": issued_on.isoformat(),
             "note": "deterministic placeholder, not forecast science"},
    )


class SimulatorProvider(WeatherProvider):
    provider_id = "simulated"
    is_simulated = True

    def fetch_forecast(self, farm: Farm, days: int,
                       issued_at: datetime) -> list[ForecastDay]:
        start = issued_at.date()
        return [simulate_day(farm.id, start, start + timedelta(days=i))
                for i in range(days)]
