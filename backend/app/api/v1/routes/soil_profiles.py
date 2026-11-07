"""Module 5 extension — Soil Profile endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.schemas.crop import SoilProfileCreate, SoilProfileListOut, SoilProfileOut
from app.services import crop_service, farm_service

router = APIRouter()

RequiresSoilRead = Annotated[set[str], Depends(require_permissions("soil_profile.read"))]
RequiresSoilManage = Annotated[set[str], Depends(require_permissions("soil_profile.manage"))]


@router.get("", response_model=SoilProfileListOut)
def list_soil_profiles(
    farm_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresSoilRead,
):
    """List soil profiles configured for a farm."""
    farm_service.get_accessible_farm(db, farm_id, current_user, "read", held)
    items = crop_service.list_soil_profiles_for_farm(db, farm_id)
    return {"items": [SoilProfileOut.model_validate(p) for p in items]}


@router.post("", response_model=SoilProfileOut, status_code=201)
def create_soil_profile(
    payload: SoilProfileCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresSoilManage,
):
    """Define a soil physical profile (field capacity, wilting point) for a farm."""
    farm_service.get_accessible_farm(db, payload.farm_id, current_user, "update", held)
    profile = crop_service.create_soil_profile(
        db,
        farm_id=payload.farm_id,
        name=payload.name,
        texture_type=payload.texture_type,
        field_capacity=payload.field_capacity,
        wilting_point=payload.wilting_point,
        saturation=payload.saturation,
        intake_rate_mm_per_hour=payload.intake_rate_mm_per_hour,
        ph=payload.ph,
        ec_ds_m=payload.electrical_conductivity_ds_m,
        description=payload.description,
        actor_id=current_user.id,
        ip_address=client_ip(request),
    )
    return SoilProfileOut.model_validate(profile)


@router.get("/{profile_id}", response_model=SoilProfileOut)
def get_soil_profile(
    profile_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresSoilRead,
):
    """Retrieve single soil profile."""
    profile = crop_service.get_soil_profile_by_id(db, profile_id)
    farm_service.get_accessible_farm(db, profile.farm_id, current_user, "read", held)
    return SoilProfileOut.model_validate(profile)
