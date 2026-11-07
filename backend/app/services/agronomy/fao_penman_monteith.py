"""FAO-56 Penman-Monteith Reference Evapotranspiration (ET0) Engine.

Scientifically validated implementation of the FAO Irrigation and Drainage
Paper No. 56 standard reference evapotranspiration methodology.
Considers temperature, humidity, solar radiation, wind speed, elevation,
and geographical latitude.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class PenmanMonteithInput:
    """Input parameters for FAO-56 daily Penman-Monteith ET0 calculation."""

    latitude_deg: float
    elevation_m: float
    day_of_year: int  # 1 to 365/366
    temp_max_c: float
    temp_min_c: float
    # Humidity: either (rh_max, rh_min) or rh_mean
    rh_mean_pct: float | None = None
    rh_max_pct: float | None = None
    rh_min_pct: float | None = None
    # Wind speed at 2m height in m/s
    wind_speed_2m_m_s: float = 2.0  # FAO default if missing is 2.0 m/s
    # Solar radiation in MJ/m^2/day (if measured by pyranometer)
    solar_radiation_mj_m2_day: float | None = None
    # Sunshine duration hours (alternative to Rs)
    sunshine_hours: float | None = None


@dataclass(frozen=True)
class PenmanMonteithResult:
    """Output of FAO-56 Penman-Monteith calculation with full scientific trace."""

    et0_mm_day: float
    mean_temp_c: float
    atmospheric_pressure_kpa: float
    psychrometric_constant_gamma: float
    slope_vapour_pressure_delta: float
    saturation_vapour_pressure_es: float
    actual_vapour_pressure_ea: float
    vapour_pressure_deficit_kpa: float
    extraterrestrial_radiation_ra: float
    clear_sky_radiation_rso: float
    net_solar_radiation_rns: float
    net_longwave_radiation_rnl: float
    net_radiation_rn: float
    radiation_term_mm: float
    aerodynamic_term_mm: float


# Solar constant in MJ m^-2 min^-1 (FAO-56 eq. 28)
SOLAR_CONSTANT_GSC = 0.0820
# Stefan-Boltzmann constant in MJ K^-4 m^-2 day^-1 (FAO-56 eq. 39)
STEFAN_BOLTZMANN_SIGMA = 4.903e-9
# Albedo for hypothetical grass reference crop (FAO-56 eq. 38)
REFERENCE_ALBEDO = 0.23


def calculate_penman_monteith_et0(inp: PenmanMonteithInput) -> PenmanMonteithResult:
    """Compute standard FAO-56 Penman-Monteith reference evapotranspiration (ET0) in mm/day.

    All equations follow FAO Irrigation & Drainage Paper 56 Chapter 3 verbatim.
    """
    t_max = float(inp.temp_max_c)
    t_min = float(inp.temp_min_c)
    t_mean = (t_max + t_min) / 2.0
    z = max(0.0, float(inp.elevation_m))
    phi = math.radians(float(inp.latitude_deg))
    j = int(inp.day_of_year)
    u2 = max(0.2, float(inp.wind_speed_2m_m_s))

    # 1. Atmospheric pressure P in kPa (FAO-56 eq. 7)
    p = 101.3 * math.pow((293.0 - 0.0065 * z) / 293.0, 5.26)

    # 2. Psychrometric constant gamma in kPa/°C (FAO-56 eq. 8)
    gamma = 0.665e-3 * p

    # 3. Saturation vapour pressure e°(T) in kPa (FAO-56 eq. 11, 12)
    e0_tmax = 0.6108 * math.exp((17.27 * t_max) / (t_max + 237.3))
    e0_tmin = 0.6108 * math.exp((17.27 * t_min) / (t_min + 237.3))
    es = (e0_tmax + e0_tmin) / 2.0

    # 4. Actual vapour pressure ea in kPa (FAO-56 eq. 17, 18, 19)
    if inp.rh_max_pct is not None and inp.rh_min_pct is not None:
        rh_max = max(0.0, min(100.0, float(inp.rh_max_pct)))
        rh_min = max(0.0, min(100.0, float(inp.rh_min_pct)))
        ea = (e0_tmin * (rh_max / 100.0) + e0_tmax * (rh_min / 100.0)) / 2.0
    elif inp.rh_mean_pct is not None:
        rh_mean = max(0.0, min(100.0, float(inp.rh_mean_pct)))
        ea = (rh_mean / 100.0) * es
    else:
        # If no RH data, estimate ea from t_min (dew point temp approx t_min) (FAO-56 eq. 48)
        ea = e0_tmin

    # Ensure ea does not exceed es due to sensor anomalies
    ea = min(ea, es)
    vpd = max(0.0, es - ea)

    # 5. Slope of saturation vapour pressure curve Delta in kPa/°C (FAO-56 eq. 13)
    e0_tmean = 0.6108 * math.exp((17.27 * t_mean) / (t_mean + 237.3))
    delta = (4098.0 * e0_tmean) / math.pow(t_mean + 237.3, 2)

    # 6. Extraterrestrial radiation Ra in MJ/m^2/day (FAO-56 eq. 21 to 28)
    dr = 1.0 + 0.033 * math.cos((2.0 * math.pi / 365.0) * j)
    delta_solar = 0.409 * math.sin((2.0 * math.pi / 365.0) * j - 1.39)
    tan_phi_tan_delta = -math.tan(phi) * math.tan(delta_solar)

    # Sunset hour angle omega_s in radians (FAO-56 eq. 25)
    if tan_phi_tan_delta >= 1.0:
        omega_s = 0.0  # Polar night
    elif tan_phi_tan_delta <= -1.0:
        omega_s = math.pi  # Polar day
    else:
        omega_s = math.acos(tan_phi_tan_delta)

    ra = (
        (24.0 * 60.0 / math.pi)
        * SOLAR_CONSTANT_GSC
        * dr
        * (
            omega_s * math.sin(phi) * math.sin(delta_solar)
            + math.cos(phi) * math.cos(delta_solar) * math.sin(omega_s)
        )
    )
    ra = max(0.1, ra)

    # Daylight hours N (FAO-56 eq. 34)
    daylight_hours = (24.0 / math.pi) * omega_s

    # 7. Clear sky solar radiation Rso in MJ/m^2/day (FAO-56 eq. 37)
    rso = (0.75 + 2.0e-5 * z) * ra

    # 8. Solar radiation Rs in MJ/m^2/day
    if inp.solar_radiation_mj_m2_day is not None and inp.solar_radiation_mj_m2_day > 0:
        rs = float(inp.solar_radiation_mj_m2_day)
    elif inp.sunshine_hours is not None and daylight_hours > 0:
        # Angstrom formula (FAO-56 eq. 35): Rs = (as + bs * n/N) * Ra with as=0.25, bs=0.50
        n_hours = max(0.0, min(daylight_hours, float(inp.sunshine_hours)))
        rs = (0.25 + 0.50 * (n_hours / daylight_hours)) * ra
    else:
        # Hargreaves-Samani temperature difference formula (FAO-56 eq. 50)
        # kRs = 0.16 for interior locations, 0.19 for coastal
        k_rs = 0.16
        temp_diff = max(0.1, t_max - t_min)
        rs = k_rs * math.sqrt(temp_diff) * ra

    # Rs cannot exceed clear sky radiation
    rs = max(0.1, min(rs, rso * 1.05))

    # 9. Net solar radiation Rns in MJ/m^2/day (FAO-56 eq. 38)
    rns = (1.0 - REFERENCE_ALBEDO) * rs

    # 10. Net longwave radiation Rnl in MJ/m^2/day (FAO-56 eq. 39)
    t_max_k4 = math.pow(t_max + 273.16, 4)
    t_min_k4 = math.pow(t_min + 273.16, 4)
    cloud_factor = 1.35 * min(1.0, rs / max(0.1, rso)) - 0.35
    cloud_factor = max(0.05, min(1.0, cloud_factor))
    humidity_factor = max(0.05, 0.34 - 0.14 * math.sqrt(max(0.0, ea)))

    rnl = STEFAN_BOLTZMANN_SIGMA * ((t_max_k4 + t_min_k4) / 2.0) * humidity_factor * cloud_factor
    rnl = max(0.0, rnl)

    # 11. Net radiation Rn in MJ/m^2/day (FAO-56 eq. 40)
    rn = rns - rnl

    # 12. Soil heat flux G is negligible for daily calculation step (FAO-56 eq. 42)
    g = 0.0

    # 13. Penman-Monteith full equation (FAO-56 eq. 6)
    # Numerator term 1: Radiation term
    term_rad = 0.408 * delta * (rn - g)
    # Numerator term 2: Aerodynamic term
    term_aero = gamma * (900.0 / (t_mean + 273.0)) * u2 * vpd
    # Denominator
    denom = delta + gamma * (1.0 + 0.34 * u2)

    et0 = (term_rad + term_aero) / denom
    # Physical sanity bounds: ET0 is non-negative and typically <= 15 mm/day
    et0 = max(0.0, min(18.0, et0))

    return PenmanMonteithResult(
        et0_mm_day=round(et0, 2),
        mean_temp_c=round(t_mean, 2),
        atmospheric_pressure_kpa=round(p, 2),
        psychrometric_constant_gamma=round(gamma, 4),
        slope_vapour_pressure_delta=round(delta, 4),
        saturation_vapour_pressure_es=round(es, 4),
        actual_vapour_pressure_ea=round(ea, 4),
        vapour_pressure_deficit_kpa=round(vpd, 4),
        extraterrestrial_radiation_ra=round(ra, 2),
        clear_sky_radiation_rso=round(rso, 2),
        net_solar_radiation_rns=round(rns, 2),
        net_longwave_radiation_rnl=round(rnl, 2),
        net_radiation_rn=round(rn, 2),
        radiation_term_mm=round(term_rad / denom, 2),
        aerodynamic_term_mm=round(term_aero / denom, 2),
    )


def calculate_daily_et0(
    latitude: float | Decimal,
    elevation_m: float | Decimal,
    target_date: date,
    temp_max: float | Decimal,
    temp_min: float | Decimal,
    rh_mean: float | Decimal | None = None,
    rh_max: float | Decimal | None = None,
    rh_min: float | Decimal | None = None,
    wind_speed: float | Decimal = 2.0,
    solar_radiation_mj: float | Decimal | None = None,
) -> PenmanMonteithResult:
    """Convenience wrapper converting common date/decimal objects to PenmanMonteithInput."""
    day_of_year = target_date.timetuple().tm_yday
    inp = PenmanMonteithInput(
        latitude_deg=float(latitude),
        elevation_m=float(elevation_m),
        day_of_year=day_of_year,
        temp_max_c=float(temp_max),
        temp_min_c=float(temp_min),
        rh_mean_pct=float(rh_mean) if rh_mean is not None else None,
        rh_max_pct=float(rh_max) if rh_max is not None else None,
        rh_min_pct=float(rh_min) if rh_min is not None else None,
        wind_speed_2m_m_s=float(wind_speed) if wind_speed is not None else 2.0,
        solar_radiation_mj_m2_day=float(solar_radiation_mj) if solar_radiation_mj is not None else None,
    )
    return calculate_penman_monteith_et0(inp)
