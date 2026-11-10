"""Module 2 — irrigation zone endpoints (nested under farms + direct by-id)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import (
    CurrentUser,
    DbSession,
    HeldPermissions,
    client_ip,
    require_permissions,
)
from app.schemas.farm import (
    ZoneControlOut,
    ZoneControlRequest,
    ZoneCreate,
    ZoneOut,
    ZoneUpdate,
)
from app.services import control_service, farm_service

router = APIRouter()

RequiresZoneRead = Annotated[set[str], Depends(require_permissions("zone.read"))]
RequiresZoneCreate = Annotated[set[str], Depends(require_permissions("zone.create"))]
RequiresZoneUpdate = Annotated[set[str], Depends(require_permissions("zone.update"))]
RequiresZoneDelete = Annotated[set[str], Depends(require_permissions("zone.delete"))]


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


@router.post("/zones/{zone_id}/control", response_model=ZoneControlOut)
def set_zone_control(
    zone_id: int,
    payload: ZoneControlRequest,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: HeldPermissions,
):
    zone, command, message = control_service.set_zone_control(
        db,
        zone_id,
        current_user,
        held,
        payload.action,
        control_mode=payload.control_mode,
        schedule_id=payload.schedule_id,
        ip_address=client_ip(request),
    )
    result = ZoneControlOut.model_validate(zone)
    result.command_id = command.id if command is not None else None
    result.command_status = command.status.value if command is not None else None
    result.control_message = message
    return result


@router.delete("/zones/{zone_id}", status_code=204)
def delete_zone(
    zone_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresZoneDelete,
):
    farm_service.delete_zone(db, zone_id, current_user, held, ip_address=client_ip(request))
