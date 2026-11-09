"""Module 2 — irrigation zone endpoints (nested under farms + direct by-id)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.core.permissions import satisfies
from app.schemas.farm import ZoneControlRequest, ZoneCreate, ZoneOut, ZoneUpdate
from app.services import farm_service

router = APIRouter()

RequiresZoneRead = Annotated[set[str], Depends(require_permissions("zone.read"))]
RequiresZoneCreate = Annotated[set[str], Depends(require_permissions("zone.create"))]
RequiresZoneUpdate = Annotated[set[str], Depends(require_permissions("zone.update"))]
RequiresZoneDelete = Annotated[set[str], Depends(require_permissions("zone.delete"))]


def _require_zone_control_or_valve(held: set[str]) -> set[str]:
    if not (
        satisfies("zone.update", held)
        or satisfies("valve.control", held)
        or satisfies("estop.trigger", held)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="missing permissions: zone.update or valve.control or estop.trigger",
        )
    return held


RequiresZoneControl = Annotated[set[str], Depends(_require_zone_control_or_valve)]


@router.get("/farms/{farm_id}/zones", response_model=list[ZoneOut])
def list_zones(
    farm_id: int, db: DbSession, current_user: CurrentUser, held: RequiresZoneRead
):
    zones = farm_service.list_zones(db, farm_id, current_user, held)
    return [ZoneOut.model_validate(z) for z in zones]


@router.post("/farms/{farm_id}/zones", response_model=ZoneOut, status_code=201)
def create_zone(
    farm_id: int,
    payload: ZoneCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresZoneCreate,
):
    zone = farm_service.create_zone(
        db, farm_id, payload, current_user, held, ip_address=client_ip(request)
    )
    return ZoneOut.model_validate(zone)


@router.get("/zones/{zone_id}", response_model=ZoneOut)
def get_zone(zone_id: int, db: DbSession, current_user: CurrentUser, held: RequiresZoneRead):
    zone = farm_service.get_zone(db, zone_id, current_user, held, farm_action="read")
    return ZoneOut.model_validate(zone)


@router.patch("/zones/{zone_id}", response_model=ZoneOut)
def update_zone(
    zone_id: int,
    payload: ZoneUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresZoneUpdate,
):
    zone = farm_service.update_zone(
        db, zone_id, payload, current_user, held, ip_address=client_ip(request)
    )
    return ZoneOut.model_validate(zone)


@router.get("/zones/{zone_id}/control", response_model=ZoneOut)
def get_zone_control(
    zone_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresZoneRead,
):
    zone = farm_service.get_zone(db, zone_id, current_user, held, farm_action="read")
    return ZoneOut.model_validate(zone)


@router.post("/zones/{zone_id}/control", response_model=ZoneOut)
def set_zone_control(
    zone_id: int,
    payload: ZoneControlRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresZoneControl,
):
    zone = farm_service.set_zone_runtime(
        db,
        zone_id,
        current_user,
        held,
        payload.action,
        control_mode=payload.control_mode,
        ip_address=client_ip(request),
    )
    return ZoneOut.model_validate(zone)


@router.delete("/zones/{zone_id}", status_code=204)
def delete_zone(
    zone_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresZoneDelete,
):
    farm_service.delete_zone(db, zone_id, current_user, held, ip_address=client_ip(request))
