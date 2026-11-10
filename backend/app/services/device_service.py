"""Module 9 (Phase 2) — device registry business logic.

Authorization model: devices hang off farms, so every operation re-uses the
tested farm access rules (`farm_service.get_accessible_farm`): managing a
device requires farm-update access on its farm, reading requires farm-read
access. Cross-owner device ids return 404, never 403 (no enumeration).
"""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.permissions import satisfies
from app.core.security import generate_device_key, hash_device_key, verify_device_key
from app.models.farm import Farm, IrrigationZone
from app.models.iot import (
    Device,
    DeviceCommand,
    DeviceCommandStatus,
    DeviceFaultEvent,
    DeviceStatus,
    DeviceType,
)
from app.models.schedule import IrrigationSchedule, ScheduleStatus
from app.models.user import User
from app.services import audit_service, farm_service

DEVICE_ACTIONS = ("read", "manage")


def utcnow_naive() -> datetime:
    """Naive-UTC now, the codebase-wide timestamp convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Registration / key lifecycle
# ---------------------------------------------------------------------------

def _issue_key(device: Device) -> str:
    """Assign a fresh machine credential; returns the ONE-TIME plaintext."""
    plaintext = generate_device_key()
    device.key_hash = hash_device_key(plaintext)
    device.key_prefix = plaintext[:13]
    device.key_issued_at = utcnow_naive()
    return plaintext


def register_device(
    db: Session, payload, user: User, held: set[str], ip_address: str = ""
) -> tuple[Device, str]:
    """Register a device, or RE-register an existing code on the same farm.

    Re-register (same farm + code, e.g. reflashing a field unit) rotates the
    API key: the old key stops working immediately, metadata is refreshed,
    a revoked device returns to active, and the new plaintext key is
    returned once — matching the physical re-provisioning workflow.
    """
    farm = farm_service.get_accessible_farm(db, payload.farm_id, user, "update", held)
    if payload.zone_id is not None:
        zone = db.get(IrrigationZone, payload.zone_id)
        if zone is None or zone.is_deleted or zone.farm_id != farm.id:
            raise NotFoundError(f"zone {payload.zone_id} not found on farm {farm.id}")
    code = payload.code.strip()
    existing = (
        db.query(Device)
        .filter(Device.farm_id == farm.id, Device.code == code,
                Device.is_deleted.is_(False))
        .first()
    )
    effective_zone_id = payload.zone_id or (existing.zone_id if existing else None)
    if existing is not None and existing.device_type == DeviceType.irrigation_controller:
        old_zone = db.get(IrrigationZone, existing.zone_id) if existing.zone_id else None
        pending = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_id == existing.id,
                DeviceCommand.command == "zone_control",
                DeviceCommand.status.in_(
                    [DeviceCommandStatus.queued, DeviceCommandStatus.sent]
                ),
            )
            .first()
        )
        if old_zone is not None and (old_zone.is_running or pending is not None):
            from app.core.exceptions import BusinessRuleError

            raise BusinessRuleError(
                "stop the zone and resolve pending commands before re-registering its controller"
            )
    if payload.device_type == DeviceType.irrigation_controller:
        if effective_zone_id is None:
            from app.core.exceptions import ValidationError

            raise ValidationError("irrigation controllers must be assigned to a zone")
        other_controller = (
            db.query(Device)
            .filter(
                Device.farm_id == farm.id,
                Device.zone_id == effective_zone_id,
                Device.device_type == DeviceType.irrigation_controller,
                Device.status == DeviceStatus.active,
                Device.is_deleted.is_(False),
                Device.id != (existing.id if existing else -1),
            )
            .first()
        )
        if other_controller is not None:
            from app.core.exceptions import ConflictError

            raise ConflictError("zone already has an active irrigation controller")
    if existing:
        # Re-register: rotate key + refresh mutable metadata on the spot.
        plaintext = _issue_key(existing)
        existing.status = DeviceStatus.active
        existing.name = payload.name.strip()
        existing.device_type = payload.device_type
        existing.model = payload.model or ""
        existing.firmware_version = payload.firmware_version or ""
        if payload.zone_id is not None:
            existing.zone_id = payload.zone_id
        device = existing
        action = "device.reregister"
    else:
        plaintext = generate_device_key()
        device = Device(
            farm_id=farm.id,
            zone_id=payload.zone_id,
            name=payload.name.strip(),
            code=code,
            device_type=payload.device_type,
            status=DeviceStatus.active,
            key_hash=hash_device_key(plaintext),
            key_prefix=plaintext[:13],
            key_issued_at=utcnow_naive(),
            model=payload.model or "",
            firmware_version=payload.firmware_version or "",
        )
        db.add(device)
        db.flush()
        action = "device.register"
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action=action,
        resource_type="device", resource_id=device.id,
        details={"farm_id": farm.id, "code": device.code,
                 "type": device.device_type.value, "key_prefix": device.key_prefix},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(device)
    return device, plaintext


def authenticate_device_key(db: Session, api_key: str | None) -> Device:
    """Resolve an ACTIVE, non-deleted device from a presented plaintext key.

    Raises AuthenticationError otherwise. Shared by the HTTP device-key
    header path (app.api.deps) and the MQTT channel handler, so every
    transport authenticates machines identically: SHA-256 digest lookup +
    constant-time re-verification; revocation takes effect immediately.
    """
    unauthorized = AuthenticationError("invalid device key")
    if not api_key or not isinstance(api_key, str):
        raise unauthorized
    device = (
        db.query(Device)
        .filter(Device.key_hash == hash_device_key(api_key),
                Device.is_deleted.is_(False))
        .first()
    )
    # Defensive constant-time re-verification (guards a corrupted digest row).
    if device is None or not verify_device_key(api_key, device.key_hash):
        raise unauthorized
    if device.status != DeviceStatus.active:
        raise AuthenticationError("device credentials revoked")
    return device


def get_accessible_device(
    db: Session, device_id: int, user: User, held: set[str], action: str
) -> Device:
    """action: 'read' (farm read access) or 'manage' (farm update access)."""
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.is_deleted.is_(False))
        .first()
    )
    if device is None:
        raise NotFoundError(f"device {device_id} not found")
    farm_action = "read" if action == "read" else "update"
    farm_service.get_accessible_farm(db, device.farm_id, user, farm_action, held)
    return device


def rotate_key(
    db: Session, device_id: int, user: User, held: set[str], ip_address: str = ""
) -> tuple[Device, str]:
    device = get_accessible_device(db, device_id, user, held, "manage")
    if device.device_type == DeviceType.irrigation_controller:
        zone = db.get(IrrigationZone, device.zone_id) if device.zone_id else None
        pending = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_id == device.id,
                DeviceCommand.command == "zone_control",
                DeviceCommand.status.in_(
                    [DeviceCommandStatus.queued, DeviceCommandStatus.sent]
                ),
            )
            .first()
        )
        if zone is not None and (zone.is_running or pending is not None):
            from app.core.exceptions import BusinessRuleError

            raise BusinessRuleError(
                "stop the zone and resolve pending commands before rotating its controller key"
            )
    plaintext = _issue_key(device)
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="device.rotate_key",
        resource_type="device", resource_id=device.id,
        details={"key_prefix": device.key_prefix}, ip_address=ip_address,
    )
    db.commit()
    db.refresh(device)
    return device, plaintext


def revoke_device(
    db: Session, device_id: int, user: User, held: set[str], ip_address: str = ""
) -> Device:
    device = get_accessible_device(db, device_id, user, held, "manage")
    if device.device_type == DeviceType.irrigation_controller:
        zone = db.get(IrrigationZone, device.zone_id) if device.zone_id else None
        pending = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_id == device.id,
                DeviceCommand.command == "zone_control",
                DeviceCommand.status.in_(
                    [DeviceCommandStatus.queued, DeviceCommandStatus.sent]
                ),
            )
            .first()
        )
        if zone is not None and (zone.is_running or pending is not None):
            from app.core.exceptions import BusinessRuleError

            raise BusinessRuleError(
                "stop the zone and resolve pending commands before revoking its controller"
            )
    device.status = DeviceStatus.revoked
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="device.revoke",
        resource_type="device", resource_id=device.id,
        details={"farm_id": device.farm_id, "code": device.code},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(device)
    return device


def update_device(
    db: Session, device_id: int, payload, user: User, held: set[str],
    ip_address: str = "",
) -> Device:
    device = get_accessible_device(db, device_id, user, held, "manage")
    data = payload.model_dump(exclude_unset=True)
    if "zone_id" in data and data["zone_id"] is not None:
        zone = db.get(IrrigationZone, data["zone_id"])
        if zone is None or zone.is_deleted or zone.farm_id != device.farm_id:
            raise NotFoundError("zone not found on the device's farm")
    if device.device_type == DeviceType.irrigation_controller and "zone_id" in data:
        old_zone = db.get(IrrigationZone, device.zone_id) if device.zone_id else None
        pending = (
            db.query(DeviceCommand)
            .filter(
                DeviceCommand.device_id == device.id,
                DeviceCommand.command == "zone_control",
                DeviceCommand.status.in_(
                    [DeviceCommandStatus.queued, DeviceCommandStatus.sent]
                ),
            )
            .first()
        )
        if old_zone is not None and (old_zone.is_running or pending is not None):
            from app.core.exceptions import BusinessRuleError

            raise BusinessRuleError(
                "stop the zone and resolve pending commands before moving its controller"
            )
        new_zone_id = data["zone_id"]
        if new_zone_id is None:
            from app.core.exceptions import ValidationError

            raise ValidationError("irrigation controllers must remain assigned to a zone")
        other_controller = (
            db.query(Device)
            .filter(
                Device.farm_id == device.farm_id,
                Device.zone_id == new_zone_id,
                Device.device_type == DeviceType.irrigation_controller,
                Device.status == DeviceStatus.active,
                Device.is_deleted.is_(False),
                Device.id != device.id,
            )
            .first()
        )
        if other_controller is not None:
            from app.core.exceptions import ConflictError

            raise ConflictError("zone already has an active irrigation controller")
    for field, value in data.items():
        setattr(device, field, value)
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="device.update",
        resource_type="device", resource_id=device.id,
        details={"fields": sorted(data.keys())}, ip_address=ip_address,
    )
    db.commit()
    db.refresh(device)
    return device


# ---------------------------------------------------------------------------
# Listing + computed status
# ---------------------------------------------------------------------------

def list_devices(
    db: Session, user: User, held: set[str], *, farm_id: int | None,
    limit: int, offset: int,
) -> tuple[list[Device], int]:
    q = db.query(Device).join(Farm, Farm.id == Device.farm_id).filter(
        Device.is_deleted.is_(False), Farm.is_deleted.is_(False)
    )
    if farm_id is not None:
        farm_service.get_accessible_farm(db, farm_id, user, "read", held)
        q = q.filter(Device.farm_id == farm_id)
    elif not satisfies("farm.read.all", held):
        q = q.filter(Farm.owner_id == user.id)
    total = q.count()
    items = q.order_by(Device.id).limit(limit).offset(offset).all()
    return items, total


def is_device_stale(device: Device, now: datetime | None = None) -> bool:
    """Active device with no accepted reading for >= TELEMETRY_STALE_MINUTES.
    A never-reported device is stale only once its own age passes the same
    threshold (a device registered seconds ago is expected to be quiet)."""
    settings = get_settings()
    now = now or utcnow_naive()
    if device.status != DeviceStatus.active:
        return False
    ref = device.last_seen_at or device.created_at
    age_minutes = (now - ref).total_seconds() / 60.0
    return age_minutes > settings.TELEMETRY_STALE_MINUTES


def minutes_since_seen(device: Device, now: datetime | None = None) -> int | None:
    now = now or utcnow_naive()
    ref = device.last_seen_at
    if ref is None:
        return None
    return int((now - ref).total_seconds() // 60)


def get_control_stale_seconds() -> float:
    """Control devices must report a recent authenticated heartbeat."""
    return get_settings().TELEMETRY_STALE_MINUTES * 60


def record_device_heartbeat(device: Device) -> Device:
    if device.device_type != DeviceType.irrigation_controller:
        from app.core.exceptions import ValidationError

        raise ValidationError("heartbeat endpoint is reserved for irrigation controllers")
    device.last_seen_at = utcnow_naive()
    return device


def enqueue_zone_control_command(
    db: Session,
    device: Device,
    zone: IrrigationZone,
    action: str,
    payload: dict | None = None,
    *,
    expires_at: datetime | None = None,
) -> DeviceCommand:
    """Persist one authenticated, zone-bound control command for gateway polling."""
    if (
        device.device_type != DeviceType.irrigation_controller
        or device.zone_id != zone.id
        or device.farm_id != zone.farm_id
        or device.status != DeviceStatus.active
        or device.is_deleted
    ):
        from app.core.exceptions import BusinessRuleError

        raise BusinessRuleError("control command target is not an active controller for this zone")
    payload = payload or {}
    now = utcnow_naive()
    item = DeviceCommand(
        device_id=device.id,
        farm_id=device.farm_id,
        zone_id=zone.id,
        control_action=action,
        command="zone_control",
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        status=DeviceCommandStatus.queued,
        attempts=0,
        sent_at=None,
        expires_at=expires_at,
        correlation_id=f"{device.id}-{uuid4().hex[:12]}",
    )
    db.add(item)
    db.flush()
    db.refresh(item)
    return item


def list_pending_device_commands(
    db: Session, device: Device, *, limit: int = 50
) -> list[DeviceCommand]:
    if device.device_type != DeviceType.irrigation_controller:
        from app.core.exceptions import ValidationError

        raise ValidationError("command polling is reserved for irrigation controllers")
    now = utcnow_naive()
    retry_before = now - timedelta(seconds=30)
    items = (
        db.query(DeviceCommand)
        .filter(
            DeviceCommand.device_id == device.id,
            DeviceCommand.status.in_(
                [DeviceCommandStatus.queued, DeviceCommandStatus.sent]
            ),
            or_(
                DeviceCommand.status == DeviceCommandStatus.queued,
                DeviceCommand.sent_at <= retry_before,
            ),
        )
        .order_by(DeviceCommand.id)
        .limit(limit)
        .all()
    )
    for item in items:
        if item.expires_at is not None and item.expires_at <= now:
            item.status = DeviceCommandStatus.expired
            if item.zone_id is not None:
                zone = db.get(IrrigationZone, item.zone_id)
                if zone is not None:
                    zone.emergency_stop = True
                    audit_service.log(
                        db,
                        user_id=None,
                        actor_label=f"device:{device.code}",
                        action="zone.control.expired",
                        resource_type="irrigation_zone",
                        resource_id=zone.id,
                        details={"command_id": item.id, "action": item.control_action},
                    )
        else:
            item.status = DeviceCommandStatus.sent
            item.sent_at = now
            item.attempts += 1
    device.last_seen_at = now
    db.commit()
    for item in items:
        db.refresh(item)
    return [item for item in items if item.status == DeviceCommandStatus.sent]


def acknowledge_device_command(
    db: Session,
    device: Device,
    command_id: int,
    *,
    status: DeviceCommandStatus = DeviceCommandStatus.acked,
    message: str | None = None,
    observed_running: bool | None = None,
    interlocks_clear: bool | None = None,
    flow_lpm=None,
    pressure_bar=None,
) -> DeviceCommand:
    if device.device_type != DeviceType.irrigation_controller:
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("only an irrigation controller can acknowledge control commands")
    item = (
        db.query(DeviceCommand)
        .filter(
            DeviceCommand.id == command_id,
            DeviceCommand.device_id == device.id,
            DeviceCommand.command == "zone_control",
        )
        .first()
    )
    if item is None:
        raise NotFoundError(f"device command {command_id} not found")
    if item.status in {
        DeviceCommandStatus.acked,
        DeviceCommandStatus.failed,
        DeviceCommandStatus.expired,
        DeviceCommandStatus.cancelled,
    }:
        return item
    if item.status != DeviceCommandStatus.sent:
        from app.core.exceptions import BusinessRuleError

        raise BusinessRuleError(
            f"command must be delivered before acknowledgement (status: {item.status.value})"
        )
    now = utcnow_naive()
    device.last_seen_at = now
    if item.expires_at is not None and item.expires_at <= now:
        item.status = DeviceCommandStatus.expired
        if item.zone_id is not None:
            zone = db.get(IrrigationZone, item.zone_id)
            if zone is not None:
                zone.emergency_stop = True
        item.acked_at = now
        item.ack_message = "late acknowledgement received after command expiry"
        db.commit()
        db.refresh(item)
        return item
    from app.services.control_service import apply_control_ack

    return apply_control_ack(
        db,
        item,
        succeeded=status == DeviceCommandStatus.acked,
        observed_running=observed_running,
        interlocks_clear=interlocks_clear,
        flow_lpm=flow_lpm,
        pressure_bar=pressure_bar,
        message=message,
    )


def report_controller_runtime(db: Session, device: Device, report) -> IrrigationZone:
    if device.device_type != DeviceType.irrigation_controller:
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("only an irrigation controller can report zone runtime")
    zone = db.get(IrrigationZone, report.zone_id)
    if (
        zone is None
        or zone.is_deleted
        or zone.farm_id != device.farm_id
        or zone.id != device.zone_id
    ):
        raise NotFoundError("zone is not assigned to this controller")
    command = (
        db.query(DeviceCommand)
        .filter(
            DeviceCommand.id == report.start_command_id,
            DeviceCommand.device_id == device.id,
            DeviceCommand.zone_id == zone.id,
            DeviceCommand.control_action == "start",
            DeviceCommand.status == DeviceCommandStatus.acked,
        )
        .first()
    )
    if command is None:
        from app.core.exceptions import BusinessRuleError

        raise BusinessRuleError(
            "runtime report must reference a successfully acknowledged start command"
        )
    payload = json.loads(command.payload_json)
    schedule = db.get(IrrigationSchedule, payload["schedule_id"])
    if schedule is None or schedule.zone_id != zone.id:
        raise NotFoundError("the start command's schedule no longer exists")

    now = utcnow_naive()
    device.last_seen_at = now
    zone.is_running = report.is_running
    if report.flow_lpm is not None:
        zone.current_flow_lpm = report.flow_lpm
    if report.pressure_bar is not None:
        zone.pressure_bar = report.pressure_bar
    if report.is_running:
        zone.last_started_at = zone.last_started_at or now
    else:
        zone.last_stopped_at = now
        if report.completed:
            schedule.status = ScheduleStatus.completed
            schedule.actual_end_time = now
            schedule.actual_volume_m3 = report.delivered_volume_m3
        elif schedule.status == ScheduleStatus.executing:
            schedule.status = ScheduleStatus.cancelled
            schedule.actual_end_time = now
    if zone.emergency_stop and report.is_running:
        audit_action = "zone.runtime.reported_running_during_estop"
    else:
        audit_action = "zone.runtime.reported"
    audit_service.log(
        db,
        user_id=None,
        actor_label=f"device:{device.code}",
        action=audit_action,
        resource_type="irrigation_zone",
        resource_id=zone.id,
        details={
            "command_id": command.id,
            "is_running": report.is_running,
            "completed": report.completed,
            "flow_lpm": report.flow_lpm,
            "pressure_bar": report.pressure_bar,
        },
    )
    db.commit()
    db.refresh(zone)
    return zone


def list_device_commands(
    db: Session,
    device: Device,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DeviceCommand], int]:
    q = db.query(DeviceCommand).filter(DeviceCommand.device_id == device.id)
    total = q.count()
    items = q.order_by(DeviceCommand.created_at.desc()).limit(limit).offset(offset).all()
    return items, total


def list_faults(
    db: Session, user: User, held: set[str], *, farm_id: int | None,
    device_id: int | None, open_only: bool, limit: int, offset: int,
) -> tuple[list[DeviceFaultEvent], int]:
    q = (
        db.query(DeviceFaultEvent)
        .join(Farm, Farm.id == DeviceFaultEvent.farm_id)
        .filter(Farm.is_deleted.is_(False))
    )
    if not satisfies("farm.read.all", held):
        q = q.filter(Farm.owner_id == user.id)
    if farm_id is not None:
        farm_service.get_accessible_farm(db, farm_id, user, "read", held)
        q = q.filter(DeviceFaultEvent.farm_id == farm_id)
    if device_id is not None:
        get_accessible_device(db, device_id, user, held, "read")
        q = q.filter(DeviceFaultEvent.device_id == device_id)
    if open_only:
        q = q.filter(DeviceFaultEvent.open_marker == 1)
    total = q.count()
    items = (
        q.order_by(DeviceFaultEvent.detected_at.desc(), DeviceFaultEvent.id.desc())
        .limit(limit).offset(offset).all()
    )
    return items, total


def open_faults_for(db: Session, device_id: int) -> list[DeviceFaultEvent]:
    return (
        db.query(DeviceFaultEvent)
        .filter(DeviceFaultEvent.device_id == device_id,
                DeviceFaultEvent.open_marker == 1)
        .all()
    )


def build_status(db: Session, device: Device, now: datetime | None = None) -> dict:
    """{device, last_seen_minutes_ago, is_stale, open_faults} for API output."""
    return {
        "device": device,
        "last_seen_minutes_ago": minutes_since_seen(device, now),
        "is_stale": is_device_stale(device, now),
        "open_faults": open_faults_for(db, device.id),
    }
