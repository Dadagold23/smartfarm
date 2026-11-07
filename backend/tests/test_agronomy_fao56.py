"""Tests for FAO-56 Penman-Monteith ET0, Soil Water Balance, and GDD."""

import datetime
from app.services.agronomy.fao_penman_monteith import (
    PenmanMonteithInput,
    calculate_penman_monteith_et0,
    calculate_daily_et0,
)
from app.services.agronomy.soil_water_balance import (
    WaterBalanceInput,
    calculate_effective_precipitation,
    calculate_soil_water_balance,
)
from app.services.agronomy.growing_degree_days import (
    calculate_daily_gdd,
    predict_harvest_timeline,
    determine_growth_stage,
)


def test_fao56_penman_monteith_input_dataclass():
    """Verify Penman-Monteith ET0 against typical summer mid-latitude conditions."""
    inp = PenmanMonteithInput(
        latitude_deg=35.0,
        elevation_m=120.0,
        day_of_year=180,
        temp_max_c=30.0,
        temp_min_c=16.0,
        rh_mean_pct=55.0,
        wind_speed_2m_m_s=2.5,
        solar_radiation_mj_m2_day=22.0,
    )
    result = calculate_penman_monteith_et0(inp)

    # Reference ET0 should be in realistic 5.0 - 6.5 mm/day range
    assert 5.0 <= result.et0_mm_day <= 6.5
    # Verify intermediate components are returned and reasonable
    assert result.net_radiation_rn > 0.0
    assert result.vapour_pressure_deficit_kpa > 0.0
    assert result.slope_vapour_pressure_delta > 0.1
    assert result.psychrometric_constant_gamma > 0.06
    assert result.radiation_term_mm > 0.0
    assert result.aerodynamic_term_mm > 0.0


def test_fao56_daily_et0_wrapper():
    """Verify convenience wrapper calculate_daily_et0."""
    target = datetime.date(2026, 7, 1)
    result = calculate_daily_et0(
        latitude=35.0,
        elevation_m=120.0,
        target_date=target,
        temp_max=29.0,
        temp_min=15.0,
        rh_mean=50.0,
        wind_speed=2.0,
        solar_radiation_mj=20.5,
    )
    assert 4.0 <= result.et0_mm_day <= 6.5
    assert result.atmospheric_pressure_kpa > 95.0


def test_effective_precipitation_usda():
    """Verify USDA Soil Conservation Service monthly/daily effective precipitation method."""
    assert calculate_effective_precipitation(0.0) == 0.0
    # Light rainfall (4 mm) has low retention
    p_eff_light = calculate_effective_precipitation(4.0)
    assert round(p_eff_light, 2) == 1.20  # 4 * 0.3
    # Moderate rainfall (20 mm)
    p_eff_mod = calculate_effective_precipitation(20.0)
    assert round(p_eff_mod, 2) == 14.0  # 20 * 0.8 - 2.0
    # Heavy rainfall (40 mm)
    p_eff_heavy = calculate_effective_precipitation(40.0)
    assert round(p_eff_heavy, 2) == 25.5  # 18.0 + (40 - 25) * 0.5


def test_soil_water_balance_sensor_depletion():
    """Verify calculate_soil_water_balance with live sensor moisture."""
    # Silt loam: theta_fc = 0.30, theta_wp = 0.12, root_depth = 0.6 m
    # Sensor reports 15.0% moisture (near wilting point)
    inp = WaterBalanceInput(
        field_capacity_vol=0.30,
        wilting_point_vol=0.12,
        root_depth_m=0.60,
        crop_kc=1.15,
        depletion_fraction_p=0.50,
        reference_et0_mm=5.0,
        precipitation_forecast_mm=2.0,
        application_rate_mm_per_hour=10.0,
        zone_area_ha=2.0,
        irrigation_efficiency_pct=85.0,
        current_sensor_moisture_pct=15.0,
    )
    res = calculate_soil_water_balance(inp)

    # TAW = 1000 * (0.30 - 0.12) * 0.6 = 108.0 mm
    assert res.total_available_water_mm == 108.0
    # RAW is ~ 50% of TAW = ~54 mm
    assert 45.0 <= res.readily_available_water_mm <= 65.0
    # Sensor 15% -> Dr = 1000 * (0.30 - 0.15) * 0.6 = 90.0 mm
    assert res.root_zone_depletion_mm == 90.0
    # Stress threshold breached because Dr (90) > RAW (~54)
    assert res.is_stress_threshold_breached is True
    assert res.stress_coefficient_ks < 1.0
    # Net irrigation requirement should be ~ 90 mm - Peff (~0.6) + ETc (~5.75)
    assert res.net_irrigation_requirement_mm > 80.0
    assert res.gross_irrigation_requirement_mm > res.net_irrigation_requirement_mm
    assert res.recommended_runtime_minutes > 0
    assert res.recommended_volume_m3 > 0.0


def test_growing_degree_days():
    """Verify daily GDD calculation with base and cutoff temperatures."""
    # Maize: Tbase = 10°C, Tcutoff = 30°C
    # Day 1: Tmax = 28°C, Tmin = 16°C -> Tmean = 22°C -> GDD = 12
    gdd1 = calculate_daily_gdd(temp_max_c=28.0, temp_min_c=16.0, base_temp_c=10.0, cutoff_temp_c=30.0)
    assert gdd1 == 12.0

    # Day 2: Cold day (Tmax = 12°C, Tmin = 6°C) -> Tmin capped at 10 -> Tmean = 11 -> GDD = 1
    gdd2 = calculate_daily_gdd(temp_max_c=12.0, temp_min_c=6.0, base_temp_c=10.0, cutoff_temp_c=30.0)
    assert gdd2 == 1.0


def test_harvest_timeline_prediction():
    """Verify Module 22 harvest maturity prediction dates."""
    planting = datetime.date(2026, 4, 1)
    maturity_date, win_start, win_end = predict_harvest_timeline(
        planting_date=planting,
        standard_maturity_days=100,
        growth_acceleration_factor=1.0,
    )
    assert maturity_date == datetime.date(2026, 7, 10)
    assert win_start < maturity_date
    assert win_end > maturity_date
    assert (win_end - win_start).days >= 10


def test_determine_growth_stage():
    """Verify stage identification and Kc assignment based on stage progression."""
    stages = [
        {"stage_name": "initial", "stage_order": 1, "duration_days": 20, "kc_coefficient": 0.40},
        {"stage_name": "development", "stage_order": 2, "duration_days": 35, "kc_coefficient": 0.80},
        {"stage_name": "mid_season", "stage_order": 3, "duration_days": 40, "kc_coefficient": 1.15},
        {"stage_name": "late_season", "stage_order": 4, "duration_days": 25, "kc_coefficient": 0.60},
    ]

    # Day 15 -> initial
    name, kc = determine_growth_stage(15, 120, stages)
    assert name == "initial"
    assert kc == 0.40

    # Day 40 -> development (20 + 35 = 55)
    name, kc = determine_growth_stage(40, 120, stages)
    assert name == "development"
    assert kc == 0.80

    # Day 75 -> mid_season (20 + 35 + 40 = 95)
    name, kc = determine_growth_stage(75, 120, stages)
    assert name == "mid_season"
    assert kc == 1.15

    # Day 130 -> past end -> late_season
    name, kc = determine_growth_stage(130, 120, stages)
    assert name == "late_season"
    assert kc == 0.60
