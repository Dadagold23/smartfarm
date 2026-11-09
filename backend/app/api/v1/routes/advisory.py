"""Module 10 — AI Agricultural Advisory endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, require_permissions
from app.schemas.advisory import AdvisoryGenerateIn, AdvisoryOut
from app.services import advisory_service, farm_service

router = APIRouter()

RequiresAdvisoryGenerate = Annotated[
    set[str], Depends(require_permissions("advisory.generate"))
]


@router.get("", response_model=AdvisoryOut)
def get_advisory(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresAdvisoryGenerate,
    farm_id: int,
    zone_id: int | None = None,
):
    """Generate a field-aware advisory based on live farm status and agronomic observations."""
    farm_service.get_accessible_farm(db, farm_id, current_user, "read", held)
    insight = advisory_service.generate_zone_advisory(db, farm_id=farm_id, zone_id=zone_id)
    return AdvisoryOut.model_validate(insight)


@router.get("/generate", response_model=AdvisoryOut)
def get_advisory_generate(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresAdvisoryGenerate,
    farm_id: int = Query(...),
    zone_id: int | None = Query(None),
):
    """Alias route that keeps the advisory generator explicit and query-driven."""
    return get_advisory(
        farm_id=farm_id,
        zone_id=zone_id,
        db=db,
        current_user=current_user,
        held=held,
    )


@router.post("/generate", response_model=AdvisoryOut)
def generate_advisory(
    payload: AdvisoryGenerateIn,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresAdvisoryGenerate,
):
    """Generate an advisory from a farm zone and optional focus area."""
    farm_service.get_accessible_farm(db, payload.farm_id, current_user, "read", held)
    insight = advisory_service.generate_zone_advisory(
        db,
        farm_id=payload.farm_id,
        zone_id=payload.zone_id,
    )
    return AdvisoryOut.model_validate(insight)
