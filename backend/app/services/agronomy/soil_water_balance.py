"""FAO-56 Soil-Water Balance and Root-Zone Depletion Engine.

Calculates Total Available Water (TAW), Readily Available Water (RAW),
root-zone depletion (Dr), water stress coefficient (Ks), effective precipitation (Peff),
and required net and gross irrigation applications per agricultural zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class WaterBalanceInput:
    """Inputs to the daily root-zone soil water balance calculation."""

    # Soil hydraulic parameters
    field_capacity_vol: float  # theta_FC (e.g. 0.27 for loam)
    wilting_point_vol: float  # theta_WP (e.g. 0.12 for loam)

    # Crop parameters
    root_depth_m: float  # Zr (e.g. 0.60 m)
    crop_kc: float  # Kc coefficient for growth stage
    depletion_fraction_p: float  # FAO-56 table 22 (e.g. 0.50)

    # Weather & ET0
    reference_et0_mm: float  # from Penman-Monteith
    precipitation_forecast_mm: float  # daily expected rainfall

    # Zone properties & hardware parameters
    application_rate_mm_per_hour: float | None = None  # sprinkler rate (e.g. 12.0 mm/hr)
    zone_area_ha: float | None = None  # zone area in hectares
    irrigation_efficiency_pct: float = 85.0  # sprinkler distribution efficiency

    # Initial state / sensor observation
    initial_depletion_mm: float | None = None  # Dr from previous day balance
    current_sensor_moisture_pct: float | None = None  # measured theta (vol %) from probe


@dataclass(frozen=True)
class WaterBalanceResult:
    """Scientifically validated irrigation requirement and water balance output."""

    total_available_water_mm: float  # TAW
    readily_available_water_mm: float  # RAW
    adjusted_depletion_fraction: float  # p adjusted for ETc > 5 mm/day
    crop_etc_mm: float  # ETc = Kc * ET0
    adjusted_etc_mm: float  # ETc_adj = Ks * ETc
    effective_precipitation_mm: float  # Peff
    root_zone_depletion_mm: float  # Dr
    stress_coefficient_ks: float  # Ks (1.0 = no stress)
    depletion_pct_of_taw: float  # Dr / TAW * 100
    is_stress_threshold_breached: bool  # Dr >= RAW
    net_irrigation_requirement_mm: float  # Net application depth
    gross_irrigation_requirement_mm: float  # Accounting for system efficiency
    recommended_runtime_minutes: int  # Runtime based on application rate
    recommended_volume_m3: float  # Volume based on zone area
    metadata: dict[str, float | str | bool]


def calculate_effective_precipitation(precip_mm: float) -> float:
    """Calculate effective rainfall using the standard FAO / USDA Soil Conservation Service formula.

    Light showers (< 3-5mm) evaporate from the crop canopy before reaching root depth.
    """
    p = max(0.0, float(precip_mm))
    if p <= 0.0:
        return 0.0
    if p < 5.0:
        # Less than 5mm generally evaporates from canopy interception
        return round(p * 0.3, 2)
    elif p <= 25.0:
        # Standard FAO formula
        return round(max(0.0, p * 0.8 - 2.0), 2)
    else:
        # Heavier rain has higher runoff fraction
        return round(max(0.0, 18.0 + (p - 25.0) * 0.5), 2)


def calculate_soil_water_balance(inp: WaterBalanceInput) -> WaterBalanceResult:
    """Compute daily root-zone depletion, stress coefficient, and irrigation requirement.

    Implements FAO-56 Chapter 8 (Water balance in the root zone).
    """
    fc = float(inp.field_capacity_vol)
    wp = float(inp.wilting_point_vol)
    zr = max(0.1, float(inp.root_depth_m))
    kc = max(0.1, float(inp.crop_kc))
    p_base = max(0.1, min(0.8, float(inp.depletion_fraction_p)))
    et0 = max(0.0, float(inp.reference_et0_mm))
    precip = max(0.0, float(inp.precipitation_forecast_mm))
    efficiency = max(50.0, min(100.0, float(inp.irrigation_efficiency_pct))) / 100.0

    # 1. Total Available Water (TAW) in root zone in mm (FAO-56 eq. 82)
    # TAW = 1000 * (theta_FC - theta_WP) * Zr
    awc = max(0.02, fc - wp)
    taw = 1000.0 * awc * zr
    taw = max(5.0, round(taw, 2))

    # 2. Unstressed crop evapotranspiration ETc in mm/day (FAO-56 eq. 87)
    etc = round(kc * et0, 2)

    # 3. Adjusted depletion fraction p for high atmospheric demand (FAO-56 Table 22 footnote)
    # p = p_table + 0.04 * (5 - ETc)
    p_adj = p_base + 0.04 * (5.0 - etc)
    p_adj = max(0.10, min(0.80, round(p_adj, 2)))

    # 4. Readily Available Water (RAW) in root zone in mm (FAO-56 eq. 83)
    # RAW = p * TAW
    raw = round(p_adj * taw, 2)

    # 5. Effective precipitation (Peff)
    peff = calculate_effective_precipitation(precip)

    # 6. Current Root-Zone Depletion (Dr)
    # Can be derived from soil probe telemetry or water balance integration
    if inp.current_sensor_moisture_pct is not None and inp.current_sensor_moisture_pct > 0:
        # Convert sensor % to volume fraction (e.g. 25.0% -> 0.25)
        theta_current = float(inp.current_sensor_moisture_pct) / 100.0
        # If soil is above field capacity, Dr = 0 (soil saturated / excess draining)
        # Dr = 1000 * (theta_FC - theta_current) * Zr
        dr_sensor = 1000.0 * (fc - theta_current) * zr
        dr = max(0.0, min(taw, dr_sensor))
    elif inp.initial_depletion_mm is not None:
        # Integrate forward: Dr = Dr_prev - Peff + ETc
        dr = float(inp.initial_depletion_mm) - peff + etc
        dr = max(0.0, min(taw, dr))
    else:
        # Standard initial assumption if starting uncalibrated: 40% of RAW depleted
        dr = raw * 0.40

    dr = round(dr, 2)

    # 7. Stress coefficient Ks (FAO-56 eq. 84)
    # When Dr <= RAW, Ks = 1.0 (no water stress).
    # When Dr > RAW, Ks = (TAW - Dr) / ((1 - p) * TAW).
    if dr <= raw:
        ks = 1.0
    else:
        ks = (taw - dr) / max(0.1, (1.0 - p_adj) * taw)
        ks = max(0.0, min(1.0, round(ks, 2)))

    # Adjusted ETc under potential water stress
    etc_adj = round(ks * etc, 2)

    # 8. Irrigation trigger decision
    # Trigger threshold is reached when root zone depletion Dr >= RAW (or within 90% margin)
    is_trigger_breached = dr >= (raw * 0.95)

    # 9. Net Irrigation Requirement (Inet) in mm
    if is_trigger_breached and dr > 0.0:
        # Apply water to refill root zone back to field capacity (minus expected effective rain)
        net_irrigation = max(0.0, dr - peff)
    else:
        net_irrigation = 0.0

    net_irrigation = round(net_irrigation, 2)

    # 10. Gross Irrigation Requirement (Igross) accounting for distribution uniformity & evaporation
    if net_irrigation > 0.0:
        gross_irrigation = round(net_irrigation / efficiency, 2)
    else:
        gross_irrigation = 0.0

    # 11. Recommended runtime and volume
    rate_mm_hr = float(inp.application_rate_mm_per_hour) if inp.application_rate_mm_per_hour else 10.0
    area_ha = float(inp.zone_area_ha) if inp.zone_area_ha else 1.0

    if gross_irrigation > 0.0 and rate_mm_hr > 0.0:
        runtime_min = int(round((gross_irrigation / rate_mm_hr) * 60.0))
        # 1 mm of water on 1 hectare = 10,000 litres = 10 cubic meters (m3)
        volume_m3 = round(gross_irrigation * area_ha * 10.0, 2)
    else:
        runtime_min = 0
        volume_m3 = 0.0

    depletion_pct = round((dr / taw) * 100.0, 1)

    return WaterBalanceResult(
        total_available_water_mm=taw,
        readily_available_water_mm=raw,
        adjusted_depletion_fraction=p_adj,
        crop_etc_mm=etc,
        adjusted_etc_mm=etc_adj,
        effective_precipitation_mm=peff,
        root_zone_depletion_mm=dr,
        stress_coefficient_ks=ks,
        depletion_pct_of_taw=depletion_pct,
        is_stress_threshold_breached=is_trigger_breached,
        net_irrigation_requirement_mm=net_irrigation,
        gross_irrigation_requirement_mm=gross_irrigation,
        recommended_runtime_minutes=runtime_min,
        recommended_volume_m3=volume_m3,
        metadata={
            "formula": "FAO-56 Chapter 8 Soil Water Balance",
            "field_capacity_vol": fc,
            "wilting_point_vol": wp,
            "root_depth_m": zr,
            "depletion_fraction_base": p_base,
            "application_efficiency_pct": round(efficiency * 100.0, 1),
        },
    )
