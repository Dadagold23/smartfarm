"""Modules 12 & 22 — Planting Batches and Health Monitoring endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.models.planting import PlantingStatus
from app.schemas.planting import (
    CropHealthAssessmentCreate,
    CropHealthAssessmentListOut,
    CropHealthAssessmentOut,
    PlantingBatchCreate,
    PlantingBatchListOut,
    PlantingBatchOut,
    PlantingBatchUpdate,
)
from app.services import farm_service, lifecycle_service

router = APIRouter()

RequiresPlantingRead = Annotated[set[str], Depends(require_permissions("planting.read"))]
RequiresPlantingManage = Annotated[set[str], Depends(require_permissions("planting.manage"))]
RequiresHealthRead = Annotated[set[str], Depends(require_permissions("health.read"))]
RequiresHealthManage = Annotated[set[str], Depends(require_permissions("health.manage"))]


@router.get("", response_model=PlantingBatchListOut)
def list_plantings(
    farm_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresPlantingRead,
    zone_id: int | None = None,
    status: PlantingStatus | None = None,
):
    """List planting batches and lifecycle timelines on accessible farms."""
    farm_service.get_accessible_farm(db, farm_id, current_user, "read", held)
    items = lifecycle_service.list_plantings_for_farm(
        db, farm_id=farm_id, zone_id=zone_id, status=status
    )
    return {"items": [PlantingBatchOut.model_validate(p) for p in items]}


@router.post("", response_model=PlantingBatchOut, status_code=201)
def create_planting(
    payload: PlantingBatchCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresPlantingManage,
):
    """Register a new field planting batch with automated maturity date forecasting."""
    farm_service.get_accessible_farm(db, payload.farm_id, current_user, "update", held)
    batch = lifecycle_service.create_planting_batch(
        db,
        farm_id=payload.farm_id,
        zone_id=payload.zone_id,
        crop_id=payload.crop_id,
        batch_code=payload.batch_code,
        planting_date=payload.planting_date,
        variety_name=payload.variety_name,
        area_planted_ha=payload.area_planted_ha,
        plant_density_per_m2=payload.plant_density_per_m2,
        expected_maturity_days_override=payload.expected_maturity_days_override,
        notes=payload.notes,
        actor_id=current_user.id,
        ip_address=client_ip(request),
    )
    return PlantingBatchOut.model_validate(batch)


@router.get("/{planting_id}", response_model=PlantingBatchOut)
def get_planting(
    planting_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresPlantingRead,
):
    """Retrieve single planting batch with GDD status and predicted harvest dates."""
    batch = lifecycle_service.get_planting_batch_by_id(db, planting_id)
    farm_service.get_accessible_farm(db, batch.farm_id, current_user, "read", held)
    return PlantingBatchOut.model_validate(batch)


@router.patch("/{planting_id}", response_model=PlantingBatchOut)
def update_planting(
    planting_id: int,
    payload: PlantingBatchUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresPlantingManage,
):
    """Update planting lifecycle status, harvest date, and yields."""
    batch = lifecycle_service.get_planting_batch_by_id(db, planting_id)
    farm_service.get_accessible_farm(db, batch.farm_id, current_user, "update", held)
    updated = lifecycle_service.update_planting_status(
        db,
        planting_id=batch.id,
        status=payload.status if payload.status is not None else batch.status,
        actual_harvest_date=payload.actual_harvest_date,
        actual_yield_kg=payload.actual_yield_kg,
        notes=payload.notes,
        actor_id=current_user.id,
        ip_address=client_ip(request),
    )
    return PlantingBatchOut.model_validate(updated)


@router.get("/{planting_id}/health", response_model=CropHealthAssessmentListOut)
def list_health_assessments(
    planting_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresHealthRead,
):
    """List agronomist health assessments and stress logs for this planting."""
    batch = lifecycle_service.get_planting_batch_by_id(db, planting_id)
    farm_service.get_accessible_farm(db, batch.farm_id, current_user, "read", held)
    items = lifecycle_service.list_health_assessments_for_planting(db, batch.id)
    return {"items": [CropHealthAssessmentOut.model_validate(a) for a in items]}


@router.post("/{planting_id}/health", response_model=CropHealthAssessmentOut, status_code=201)
def create_health_assessment(
    planting_id: int,
    payload: CropHealthAssessmentCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresHealthManage,
):
    """Record a field crop health assessment (disease, water deficit, heat stress)."""
    batch = lifecycle_service.get_planting_batch_by_id(db, planting_id)
    farm_service.get_accessible_farm(db, batch.farm_id, current_user, "update", held)
    assessment = lifecycle_service.record_crop_health_assessment(
        db,
        planting_batch_id=batch.id,
        assessed_by_user_id=current_user.id,
        health_rating=payload.health_rating,
        stress_type=payload.stress_type,
        affected_area_pct=payload.affected_area_pct,
        symptoms_description=payload.symptoms_description,
        recommended_action=payload.recommended_action,
        image_url=payload.image_url,
        notes=payload.notes,
        ip_address=client_ip(request),
    )
    return CropHealthAssessmentOut.model_validate(assessment)
