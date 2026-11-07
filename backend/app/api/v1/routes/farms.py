"""Module 2 — farm endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.schemas.farm import FarmCreate, FarmOut, FarmUpdate
from app.services import farm_service

router = APIRouter()

RequiresFarmRead = Annotated[set[str], Depends(require_permissions("farm.read.own"))]
RequiresFarmCreate = Annotated[set[str], Depends(require_permissions("farm.create"))]


@router.get("", response_model=dict)
def list_farms(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresFarmRead,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: int = Query(0, ge=0),
    status: str | None = None,
    search: str | None = None,
):
    items, total = farm_service.list_farms(
        db, current_user, held, limit=limit, offset=offset, status=status, search=search
    )
    return {
        "items": [FarmOut.model_validate(f).model_dump(mode="json") for f in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.post("", response_model=FarmOut, status_code=201)
def create_farm(
    payload: FarmCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresFarmCreate,
):
    farm = farm_service.create_farm(
        db, payload, current_user, held, ip_address=client_ip(request)
    )
    return FarmOut.model_validate(farm)


@router.get("/{farm_id}", response_model=FarmOut)
def get_farm(farm_id: int, db: DbSession, current_user: CurrentUser, held: RequiresFarmRead):
    farm = farm_service.get_accessible_farm(db, farm_id, current_user, "read", held)
    return FarmOut.model_validate(farm)


@router.patch("/{farm_id}", response_model=FarmOut)
def update_farm(
    farm_id: int,
    payload: FarmUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresFarmRead,
):
    # update authorisation is enforced inside the service (own vs all).
    farm = farm_service.update_farm(
        db, farm_id, payload, current_user, held, ip_address=client_ip(request)
    )
    return FarmOut.model_validate(farm)


@router.delete("/{farm_id}", status_code=204)
def delete_farm(
    farm_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresFarmRead,
):
    farm_service.delete_farm(
        db, farm_id, current_user, held, ip_address=client_ip(request)
    )
