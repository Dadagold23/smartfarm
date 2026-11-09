"""Module 10 — AI agricultural advisory service.

Generates farm-zone recommendations grounded in current field conditions:
soil moisture, recent rainfall, crop status, and the irrigation schedule
calculated for the zone. The advice remains advisory and never directly
acts on irrigation equipment.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.crop import CropSpecies
from app.models.farm import Farm, IrrigationZone
from app.models.planting import PlantingBatch, PlantingStatus
from app.models.schedule import IrrigationSchedule, ScheduleStatus
from app.models.soil import SoilReading
from app.models.weather import WeatherObservation


def generate_zone_advisory(db: Session, farm_id: int, zone_id: int | None = None) -> dict:
    """Build a concise agronomic advisory for one farm or zone."""
    farm = db.execute(
        select(Farm).where(Farm.id == farm_id, Farm.is_deleted.is_(False))
    ).scalar_one_or_none()
    if farm is None:
        raise NotFoundError("Farm", str(farm_id))

    if zone_id is not None:
        zone = db.execute(
            select(IrrigationZone).where(
                IrrigationZone.id == zone_id,
                IrrigationZone.farm_id == farm_id,
                IrrigationZone.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        if zone is None:
            raise NotFoundError("IrrigationZone", str(zone_id))
        zones = [zone]
    else:
        zones = list(
            db.execute(
                select(IrrigationZone).where(
                    IrrigationZone.farm_id == farm_id,
                    IrrigationZone.is_deleted.is_(False),
                )
            ).scalars().all()
        )

    recommendations: list[str] = []
    zone_recommendations: list[str] = []
    risk_level = "low"

    if not zones:
        return {
            "farm_id": farm.id,
            "zone_id": None,
            "risk_level": "low",
            "summary": f"No irrigation zones are registered on {farm.name}. Add a zone before scheduling agronomic actions.",
            "recommendations": [
                "Create a zone profile with area, crop, and soil settings before planning irrigation.",
                "Register at least one active planting or crop baseline for field recommendations.",
            ],
            "source": "farm_state",
            "generated_at": datetime.utcnow(),
        }

    zone = zones[0]
    soil = db.execute(
        select(SoilReading)
        .where(SoilReading.zone_id == zone.id)
        .order_by(desc(SoilReading.measured_at))
    ).scalars().first()
    weather = db.execute(
        select(WeatherObservation)
        .where(WeatherObservation.farm_id == farm_id)
        .order_by(desc(WeatherObservation.measured_at))
    ).scalars().first()

    planting = db.execute(
        select(PlantingBatch).where(
            PlantingBatch.zone_id == zone.id,
            PlantingBatch.status == PlantingStatus.active,
            PlantingBatch.is_deleted.is_(False),
        )
    ).scalar_one_or_none()

    crop_name = "unplanted field"
    if planting is not None:
        crop = db.get(CropSpecies, planting.crop_id)
        if crop is not None:
            crop_name = crop.common_name

    last_moisture = None
    if soil is not None and soil.moisture_pct is not None:
        last_moisture = float(soil.moisture_pct)

    latest_rain = 0.0
    if weather is not None and weather.rainfall_mm is not None:
        latest_rain = float(weather.rainfall_mm)

    schedule = db.execute(
        select(IrrigationSchedule)
        .where(
            IrrigationSchedule.farm_id == farm_id,
            IrrigationSchedule.zone_id == zone.id,
            IrrigationSchedule.status.in_([ScheduleStatus.recommended, ScheduleStatus.approved, ScheduleStatus.skipped_weather]),
        )
        .order_by(desc(IrrigationSchedule.target_date), desc(IrrigationSchedule.created_at))
    ).scalars().first()

    if zone.emergency_stop:
        risk_level = "high"
        zone_recommendations.append("Emergency stop is active. Clear the stop before any manual or automated irrigation sequence.")
    if last_moisture is not None and last_moisture < 30:
        risk_level = "high"
        zone_recommendations.append(
            f"Current soil moisture is {last_moisture:.1f}% in {zone.name}; the root zone is dry and should be rechecked before irrigation begins."
        )
    elif last_moisture is not None and last_moisture < 45:
        risk_level = "moderate"
        zone_recommendations.append(
            f"Soil moisture is {last_moisture:.1f}% in {zone.name}; maintain a conservative irrigation schedule while conditions remain variable."
        )
    elif last_moisture is None:
        zone_recommendations.append(
            f"No recent soil probe reading is available for {zone.name}; verify sensor calibration and telemetry before relying on the recommendation."
        )
    else:
        zone_recommendations.append(
            f"Soil moisture remains adequate for {crop_name}; continue monitoring and avoid unnecessary irrigation events."
        )

    if latest_rain > 0:
        zone_recommendations.append(
            f"Recent rainfall totalled {latest_rain:.1f} mm; reduce or delay irrigation to avoid waterlogging and unnecessary pumping."
        )
        if risk_level == "low":
            risk_level = "moderate"
    if schedule is not None:
        if schedule.status == ScheduleStatus.skipped_weather:
            zone_recommendations.append(
                "The last schedule was skipped because weather conditions were sufficient to meet crop demand. Continue with monitoring rather than irrigation."
            )
        elif schedule.recommended_runtime_minutes > 0:
            zone_recommendations.append(
                f"The latest agronomic recommendation calls for {schedule.recommended_runtime_minutes} minutes of irrigation and {float(schedule.recommended_volume_m3):.2f} m³ of application."
            )
        else:
            zone_recommendations.append("The current zone has no active irrigation demand according to the latest water-balance calculation.")
    else:
        zone_recommendations.append(
            f"No recent irrigation schedule is available for {zone.name}; run the scheduling engine to generate a validated recommendation before manual operation."
        )

    if zone.status.value != "active":
        risk_level = "high"
        zone_recommendations.append(f"Zone {zone.name} is not active. Verify operational status before opening the irrigation circuit.")

    if zone.max_application_mm_per_hour is not None:
        zone_recommendations.append(
            f"Application cap is set to {float(zone.max_application_mm_per_hour):.2f} mm/hr; keep all planned operations within this configured safety envelope."
        )
    else:
        zone_recommendations.append("No application cap is configured for this zone; define a safe maximum before running unattended automation.")

    summary = (
        f"{farm.name} / {zone.name} is showing a {risk_level} agronomic risk profile for {crop_name}. "
        "The advisory combines soil moisture, recent weather, and the latest irrigation schedule to guide safe crop management."
    )
    recommendations = zone_recommendations[:5]

    return {
        "farm_id": farm.id,
        "zone_id": zone.id,
        "risk_level": risk_level,
        "summary": summary,
        "recommendations": recommendations,
        "source": "farm_state",
        "generated_at": datetime.utcnow(),
    }
