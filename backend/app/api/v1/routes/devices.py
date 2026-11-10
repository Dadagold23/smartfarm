"""Module 9 — device registry endpoints (user JWT side, admin/manager tooling).

All actions also enforce farm access inside `device_service` (defence in
depth): managing a device requires update access on its farm; listing is
ownership-scoped. The plaintext API key appears ONLY in register/rotate
responses — it is never stored or returned anywhere else.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import (
    CurrentUser,
    DbSession,
    client_ip,
    device_key_header,
    require_permissions,
)
from app.models.iot import DeviceCommandStatus
from app.schemas.iot import (
    DeviceCommandAck,
    DeviceCommandListOut,
    DeviceCommandOut,
    DeviceCreate,
    DeviceHeartbeatOut,
    ControllerRuntimeIn,
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


@router.post("/commands/pending", response_model=DeviceCommandListOut)
def poll_device_commands(
    db: DbSession,
    api_key: Annotated[str | None, Depends(device_key_header)],
):
    device = device_service.authenticate_device_key(db, api_key)
    items = device_service.list_pending_device_commands(db, device)
    return {"items": [DeviceCommandOut.model_validate(item) for item in items]}


@router.post("/heartbeat", response_model=DeviceHeartbeatOut)
def device_heartbeat(
    db: DbSession,
    api_key: Annotated[str | None, Depends(device_key_header)],
):
    device = device_service.authenticate_device_key(db, api_key)
    if device.device_type.value != "irrigation_controller":
        from app.core.exceptions import ValidationError

        raise ValidationError("heartbeat endpoint is reserved for irrigation controllers")
    device_service.record_device_heartbeat(device)
    db.commit()
    db.refresh(device)
    return {"ok": True, "last_seen_at": device.last_seen_at}


@router.post("/runtime", response_model=dict)
def report_controller_runtime(
    payload: ControllerRuntimeIn,
    db: DbSession,
    api_key: Annotated[str | None, Depends(device_key_header)],
):
    device = device_service.authenticate_device_key(db, api_key)
    zone = device_service.report_controller_runtime(db, device, payload)
    return {
        "zone_id": zone.id,
        "is_running": zone.is_running,
        "emergency_stop": zone.emergency_stop,
        "current_flow_lpm": zone.current_flow_lpm,
        "pressure_bar": zone.pressure_bar,
    }


@router.post("/commands/{command_id}/ack", response_model=DeviceCommandOut)
def acknowledge_device_command(
    command_id: int,
    payload: DeviceCommandAck,
    db: DbSession,
    api_key: Annotated[str | None, Depends(device_key_header)],
):
    device = device_service.authenticate_device_key(db, api_key)
    item = device_service.acknowledge_device_command(
        db,
        device,
        command_id,
        status=DeviceCommandStatus(payload.status),
        message=payload.message,
        observed_running=payload.observed_running,
        interlocks_clear=payload.interlocks_clear,
        flow_lpm=payload.flow_lpm,
        pressure_bar=payload.pressure_bar,
    )
    return DeviceCommandOut.model_validate(item)
