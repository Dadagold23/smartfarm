"""Module 4 — Crop Knowledge Database endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.models.crop import CropCategory, CropSpecies
from app.schemas.crop import CropSpeciesCreate, CropSpeciesListOut, CropSpeciesOut
from app.services import crop_service

router = APIRouter()

RequiresCropRead = Annotated[set[str], Depends(require_permissions("crop.read"))]
RequiresCropManage = Annotated[set[str], Depends(require_permissions("crop.manage"))]


@router.get("", response_model=CropSpeciesListOut)
def list_crops(
    db: DbSession,
    held: RequiresCropRead,
    category: CropCategory | None = None,
    query: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: int = Query(0, ge=0),
):
    """Browse or search verified crop agronomic parameters and Kc values."""
    items, total = crop_service.list_crop_species(
        db, category=category, query=query, limit=limit, offset=offset
    )
    return {
        "items": [CropSpeciesOut.model_validate(c) for c in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.post("/seed-defaults", response_model=dict)
def seed_fao_crops(
    db: DbSession,
    held: RequiresCropManage,
):
    """Seed or update standard FAO-56 crop research records."""
    count = crop_service.seed_standard_crop_database(db)
    return {"status": "ok", "seeded_crops": count}


@router.get("/{crop_id}", response_model=CropSpeciesOut)
def get_crop(
    crop_id: int,
    db: DbSession,
    held: RequiresCropRead,
):
    """Retrieve detailed crop parameters and all stage-specific Kc coefficients."""
    crop = crop_service.get_crop_species_by_id(db, crop_id)
    return CropSpeciesOut.model_validate(crop)


@router.post("", response_model=CropSpeciesOut, status_code=201)
def create_crop(
    payload: CropSpeciesCreate,
    db: DbSession,
    held: RequiresCropManage,
):
    """Add a new crop species with agronomic parameters."""
    crop = CropSpecies(
        common_name=payload.common_name.strip(),
        scientific_name=payload.scientific_name.strip(),
        category=payload.category,
        variety=payload.variety.strip(),
        description=payload.description.strip(),
        min_root_depth_m=payload.min_root_depth_m,
        max_root_depth_m=payload.max_root_depth_m,
        depletion_fraction_p=payload.depletion_fraction_p,
        yield_response_factor_ky=payload.yield_response_factor_ky,
        base_temperature_c=payload.base_temperature_c,
        cutoff_temperature_c=payload.cutoff_temperature_c,
        standard_cycle_days=payload.standard_cycle_days,
        optimal_ph_min=payload.optimal_ph_min,
        optimal_ph_max=payload.optimal_ph_max,
        salinity_threshold_ec_ds_m=payload.salinity_threshold_ec_ds_m,
        research_source=payload.research_source.strip(),
        is_verified=True,
    )
    db.add(crop)
    db.commit()
    db.refresh(crop)
    return CropSpeciesOut.model_validate(crop)
