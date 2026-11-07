"""Module 12 & Module 22 — Planting Lifecycle and Health Assessment Service.

Manages planting batches, accumulates Growing Degree Days, predicts absolute calendar
maturity and harvest dates, and logs agronomist crop health assessments.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.crop import CropGrowthStage, CropSpecies
from app.models.farm import Farm, IrrigationZone
from app.models.planting import (
    CropHealthAssessment,
    HealthRating,
    PlantingBatch,
    PlantingStatus,
    StressType,
)
from app.services.agronomy.growing_degree_days import (
    calculate_daily_gdd,
    predict_harvest_timeline,
)
from app.services.audit_service import record_audit_event


def create_planting_batch(
    db: Session,
    farm_id: int,
    zone_id: int,
    crop_id: int,
    batch_code: str,
    planting_date: date,
    variety_name: str = "",
    area_planted_ha: Decimal | None = None,
    plant_density_per_m2: Decimal | None = None,
    expected_maturity_days_override: int | None = None,
    notes: str = "",
    actor_id: int | None = None,
    ip_address: str = "",
) -> PlantingBatch:
    """Create a new planting batch, computing absolute calendar maturity dates."""
    # Verify zone belongs to farm
    zone = db.execute(
        select(IrrigationZone).where(
            IrrigationZone.id == zone_id,
            IrrigationZone.farm_id == farm_id,
            IrrigationZone.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if zone is None:
        raise ValidationError(f"IrrigationZone {zone_id} not found on farm {farm_id}")

    crop = db.execute(
        select(CropSpecies).where(CropSpecies.id == crop_id, CropSpecies.is_deleted.is_(False))
    ).scalar_one_or_none()
    if crop is None:
        raise NotFoundError("CropSpecies", str(crop_id))

    # Calculate absolute calendar maturity dates
    cycle_days = expected_maturity_days_override or crop.standard_cycle_days
    pred_maturity, window_start, window_end = predict_harvest_timeline(
        planting_date=planting_date,
        standard_maturity_days=cycle_days,
    )

    # Initial growth stage
    initial_stage = db.execute(
        select(CropGrowthStage)
        .where(CropGrowthStage.crop_id == crop_id)
        .order_by(CropGrowthStage.stage_order.asc())
    ).scalars().first()

    batch = PlantingBatch(
        farm_id=farm_id,
        zone_id=zone_id,
        crop_id=crop_id,
        current_growth_stage_id=initial_stage.id if initial_stage else None,
        batch_code=batch_code.strip(),
        variety_name=variety_name.strip() or crop.variety,
        planting_date=planting_date,
        status=PlantingStatus.active,
        expected_maturity_days=cycle_days,
        predicted_maturity_date=pred_maturity,
        harvest_window_start=window_start,
        harvest_window_end=window_end,
        area_planted_ha=area_planted_ha or zone.area_ha,
        plant_density_per_m2=plant_density_per_m2,
        notes=notes.strip(),
    )
    db.add(batch)
    db.flush()

    record_audit_event(
        db,
        action="planting.create",
        resource_type="planting_batch",
        resource_id=str(batch.id),
        user_id=actor_id,
        details={
            "farm_id": farm_id,
            "zone_id": zone_id,
            "crop": crop.common_name,
            "batch_code": batch.batch_code,
            "predicted_maturity": str(pred_maturity),
        },
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(batch)
    return batch


def list_plantings_for_farm(
    db: Session,
    farm_id: int,
    zone_id: int | None = None,
    status: PlantingStatus | None = None,
) -> Sequence[PlantingBatch]:
    """List planting batches for a farm with optional zone and status filters."""
    stmt = select(PlantingBatch).where(
        PlantingBatch.farm_id == farm_id,
        PlantingBatch.is_deleted.is_(False),
    )
    if zone_id is not None:
        stmt = stmt.where(PlantingBatch.zone_id == zone_id)
    if status is not None:
        stmt = stmt.where(PlantingBatch.status == status)

    return db.execute(stmt.order_by(desc(PlantingBatch.planting_date))).scalars().all()


def get_planting_batch_by_id(db: Session, planting_id: int) -> PlantingBatch:
    """Retrieve single planting batch by ID."""
    batch = db.execute(
        select(PlantingBatch).where(
            PlantingBatch.id == planting_id,
            PlantingBatch.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if batch is None:
        raise NotFoundError("PlantingBatch", str(planting_id))
    return batch


def update_planting_status(
    db: Session,
    planting_id: int,
    status: PlantingStatus,
    actual_harvest_date: date | None = None,
    actual_yield_kg: Decimal | None = None,
    notes: str | None = None,
    actor_id: int | None = None,
    ip_address: str = "",
) -> PlantingBatch:
    """Update planting lifecycle status (e.g. marked mature, harvested, or failed)."""
    batch = get_planting_batch_by_id(db, planting_id)
    batch.status = status
    if actual_harvest_date is not None:
        batch.actual_harvest_date = actual_harvest_date
    if actual_yield_kg is not None:
        batch.actual_yield_kg = actual_yield_kg
    if notes is not None:
        batch.notes = notes

    record_audit_event(
        db,
        action="planting.status_update",
        resource_type="planting_batch",
        resource_id=str(batch.id),
        user_id=actor_id,
        details={"new_status": status.value},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(batch)
    return batch


def record_crop_health_assessment(
    db: Session,
    planting_batch_id: int,
    assessed_by_user_id: int,
    health_rating: HealthRating,
    stress_type: StressType = StressType.none,
    affected_area_pct: Decimal | None = None,
    symptoms_description: str = "",
    recommended_action: str = "",
    image_url: str = "",
    notes: str = "",
    ip_address: str = "",
) -> CropHealthAssessment:
    """Log an agronomic field crop health assessment."""
    batch = get_planting_batch_by_id(db, planting_batch_id)

    assessment = CropHealthAssessment(
        planting_batch_id=batch.id,
        farm_id=batch.farm_id,
        zone_id=batch.zone_id,
        assessed_by_user_id=assessed_by_user_id,
        health_rating=health_rating,
        stress_type=stress_type,
        affected_area_pct=affected_area_pct,
        symptoms_description=symptoms_description.strip(),
        recommended_action=recommended_action.strip(),
        image_url=image_url.strip(),
        notes=notes.strip(),
    )
    db.add(assessment)
    db.flush()

    record_audit_event(
        db,
        action="health.assess",
        resource_type="crop_health_assessment",
        resource_id=str(assessment.id),
        user_id=assessed_by_user_id,
        details={
            "planting_id": batch.id,
            "rating": health_rating.value,
            "stress": stress_type.value,
        },
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(assessment)
    return assessment


def list_health_assessments_for_planting(
    db: Session, planting_batch_id: int
) -> Sequence[CropHealthAssessment]:
    """Retrieve all health logs for a planting batch."""
    return db.execute(
        select(CropHealthAssessment)
        .where(CropHealthAssessment.planting_batch_id == planting_batch_id)
        .order_by(desc(CropHealthAssessment.assessed_at))
    ).scalars().all()
