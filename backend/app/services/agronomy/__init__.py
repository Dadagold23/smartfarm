"""Agronomic science and computational engines package.

Provides FAO-56 Penman-Monteith reference evapotranspiration, soil-water balance,
root-zone depletion modeling, and growing degree day lifecycle tracking.
"""

from app.services.agronomy.fao_penman_monteith import (
    PenmanMonteithInput,
    PenmanMonteithResult,
    calculate_daily_et0,
    calculate_penman_monteith_et0,
)
from app.services.agronomy.growing_degree_days import (
    calculate_daily_gdd,
    determine_growth_stage,
    predict_harvest_timeline,
)
from app.services.agronomy.soil_water_balance import (
    WaterBalanceInput,
    WaterBalanceResult,
    calculate_effective_precipitation,
    calculate_soil_water_balance,
)

__all__ = [
    "calculate_penman_monteith_et0",
    "calculate_daily_et0",
    "PenmanMonteithInput",
    "PenmanMonteithResult",
    "calculate_soil_water_balance",
    "calculate_effective_precipitation",
    "WaterBalanceInput",
    "WaterBalanceResult",
    "calculate_daily_gdd",
    "predict_harvest_timeline",
    "determine_growth_stage",
]
