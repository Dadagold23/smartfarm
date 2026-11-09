"""Module 9 — device registry endpoints (user JWT side, admin/manager tooling).

All actions also enforce farm access inside `device_service` (defence in
depth): managing a device requires update access on its farm; listing is
ownership-scoped. The plaintext API key appears ONLY in register/rotate
responses — it is never stored or returned anywhere else.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.models.iot import DeviceCommandStatus
from app.schemas.iot import (
    DeviceCommandAck,
    DeviceCommandCreate,
    DeviceCommandOut,
    DeviceCreate,
    DeviceOut,
    DeviceRegisterOut,
    DeviceStatusOut,
    DeviceUpdate,
)
from app.services import device_service

router = APIRouter()

RequiresDeviceManage = Annotated[set[str], Depends(require_permissions("device.manage"))]


@router.post("", response_model=DeviceRegisterOut, status_code=201)
def register_device(
    payload: DeviceCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresDeviceManage,
):
    device, plaintext = device_service.register_device(
        db, payload, current_user, held, ip_address=client_ip(request)
    )
    return DeviceRegisterOut(
        device=DeviceOut.model_validate(device), api_key=plaintext
    )


@router.get("", response_model=dict)
def list_devices(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresDeviceManage,
    farm_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: int = Query(0, ge=0),
):
    items, total = device_service.list_devices(
        db, current_user, held, farm_id=farm_id, limit=limit, offset=offset
    )
    return {
        "items": [DeviceOut.model_validate(d).model_dump(mode="json") for d in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(
    device_id: int, db: DbSession, current_user: CurrentUser,
    held: RequiresDeviceManage,
):
    return DeviceOut.model_validate(
        device_service.get_accessible_device(db, device_id, current_user, held, "read")
    )


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
def device_status(
    device_id: int, db: DbSession, current_user: CurrentUser,
    held: RequiresDeviceManage,
):
    device = device_service.get_accessible_device(
        db, device_id, current_user, held, "read"
    )
    return DeviceStatusOut.model_validate(device_service.build_status(db, device))


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: int,
    payload: DeviceUpdate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresDeviceManage,
):
    return DeviceOut.model_validate(device_service.update_device(
        db, device_id, payload, current_user, held, ip_address=client_ip(request)
    ))


@router.post("/{device_id}/rotate-key", response_model=DeviceRegisterOut)
def rotate_key(
    device_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresDeviceManage,
):
    device, plaintext = device_service.rotate_key(
        db, device_id, current_user, held, ip_address=client_ip(request)
    )
    return DeviceRegisterOut(
        device=DeviceOut.model_validate(device), api_key=plaintext
    )


@router.post("/{device_id}/revoke", response_model=DeviceOut)
def revoke_device(
    device_id: int,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresDeviceManage,
):
    return DeviceOut.model_validate(device_service.revoke_device(
        db, device_id, current_user, held, ip_address=client_ip(request)
    ))


@router.post("/{device_id}/commands", response_model=DeviceCommandOut, status_code=201)
def enqueue_device_command(
    device_id: int,
    payload: DeviceCommandCreate,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresDeviceManage,
):
    device = device_service.get_accessible_device(db, device_id, current_user, held, "manage")
    item = device_service.enqueue_device_command(
        db,
        device,
        payload.command,
        payload.payload,
        requires_ack=payload.requires_ack,
        ttl_seconds=payload.ttl_seconds,
    )
    return DeviceCommandOut.model_validate(item)


@router.get("/{device_id}/commands", response_model=dict)
def list_device_commands(
    device_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresDeviceManage,
    limit: int = 50,
    offset: int = 0,
):
    device = device_service.get_accessible_device(db, device_id, current_user, held, "read")
    items, total = device_service.list_device_commands(db, device, limit=limit, offset=offset)
    return {
        "items": [DeviceCommandOut.model_validate(item).model_dump(mode="json") for item in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.post("/{device_id}/commands/{command_id}/ack", response_model=DeviceCommandOut)
def acknowledge_device_command(
    device_id: int,
    command_id: int,
    payload: DeviceCommandAck,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresDeviceManage,
):
    device = device_service.get_accessible_device(db, device_id, current_user, held, "manage")
    item = device_service.acknowledge_device_command(
        db,
        device,
        command_id,
        status=payload.status,
        message=payload.message,
    )
    return DeviceCommandOut.model_validate(item)
