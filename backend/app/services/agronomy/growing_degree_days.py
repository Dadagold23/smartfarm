"""Growing Degree Day (GDD) and Thermal Time Calculations.

Calculates thermal accumulation from daily temperature extrema, maps progress to
crop development stages, and computes absolute calendar maturity dates and harvest
windows per Module 22 requirements.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal


def calculate_daily_gdd(
    temp_max_c: float | Decimal,
    temp_min_c: float | Decimal,
    base_temp_c: float | Decimal = 10.0,
    cutoff_temp_c: float | Decimal | None = 30.0,
) -> float:
    """Compute daily Growing Degree Days (GDD) with standard agronomic cutoff.

    GDD = max(0.0, (Tmax + Tmin) / 2 - Tbase)
    """
    t_max = float(temp_max_c)
    t_min = float(temp_min_c)
    t_base = float(base_temp_c)

    if cutoff_temp_c is not None:
        t_cutoff = float(cutoff_temp_c)
        t_max = min(t_max, t_cutoff)
        t_min = min(t_min, t_cutoff)

    # Temperatures below base do not contribute negative development
    t_max = max(t_max, t_base)
    t_min = max(t_min, t_base)

    t_mean = (t_max + t_min) / 2.0
    gdd = max(0.0, t_mean - t_base)
    return round(gdd, 2)


def predict_harvest_timeline(
    planting_date: date,
    standard_maturity_days: int,
    growth_acceleration_factor: float = 1.0,
) -> tuple[date, date, date]:
    """Calculate absolute calendar dates for maturity and harvest window.

    Returns:
        (predicted_maturity_date, harvest_window_start, harvest_window_end)
    """
    effective_days = max(10, int(round(standard_maturity_days * growth_acceleration_factor)))
    maturity_date = planting_date + timedelta(days=effective_days)

    # Typical harvest window: begins ~5 days before peak maturity, extends 10 days after
    buffer_start_days = min(7, max(3, int(effective_days * 0.05)))
    buffer_end_days = min(15, max(7, int(effective_days * 0.10)))

    window_start = maturity_date - timedelta(days=buffer_start_days)
    window_end = maturity_date + timedelta(days=buffer_end_days)

    return maturity_date, window_start, window_end


def determine_growth_stage(
    days_elapsed: int,
    total_cycle_days: int,
    stages: list[dict],
) -> tuple[str, float]:
    """Determine current growth stage and Kc from days elapsed and stage definitions.

    stages is a list of dicts with:
    {'stage_name': 'initial', 'stage_order': 1, 'duration_days': 20, 'kc': 0.70}
    """
    if not stages:
        return "development", 1.0

    sorted_stages = sorted(stages, key=lambda s: s.get("stage_order", 0))
    cumulative_days = 0

    for st in sorted_stages:
        stage_duration = st.get("duration_days", 0)
        cumulative_days += stage_duration
        if days_elapsed <= cumulative_days:
            return st["stage_name"], float(st.get("kc_coefficient", 1.0))

    # Past total planned cycle days => late season / maturity stage
    last_stage = sorted_stages[-1]
    return last_stage["stage_name"], float(last_stage.get("kc_coefficient", 0.8))
