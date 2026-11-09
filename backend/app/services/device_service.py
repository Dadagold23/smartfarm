"""Module 9 (Phase 2) — device registry business logic.

Authorization model: devices hang off farms, so every operation re-uses the
tested farm access rules (`farm_service.get_accessible_farm`): managing a
device requires farm-update access on its farm, reading requires farm-read
access. Cross-owner device ids return 404, never 403 (no enumeration).
"""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.permissions import satisfies
from app.core.security import generate_device_key, hash_device_key, verify_device_key
from app.iot.bus import BusCredentials, get_bus
from app.iot.topics import build_command_topic
from app.models.farm import Farm, IrrigationZone
from app.models.iot import Device, DeviceCommand, DeviceCommandStatus, DeviceFaultEvent, DeviceStatus
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


def enqueue_device_command(
    db: Session,
    device: Device,
    command: str,
    payload: dict | None = None,
    *,
    requires_ack: bool = True,
    ttl_seconds: int | None = 300,
) -> DeviceCommand:
    """Queue a command to a device and emit it on the fallback command bus.

    The system records the command in the database and publishes a transport
    message that mirrors the MQTT command topic contract used by the gateway.
    """
    payload = payload or {}
    now = utcnow_naive()
    expires_at = now + timedelta(seconds=max(ttl_seconds or 300, 30))
    item = DeviceCommand(
        device_id=device.id,
        farm_id=device.farm_id,
        command=command.strip()[:120],
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        status=DeviceCommandStatus.queued,
        attempts=0,
        sent_at=now,
        expires_at=expires_at,
        correlation_id=f"{device.id}-{uuid4().hex[:12]}",
    )
    db.add(item)
    db.flush()

    topic = build_command_topic(
        get_settings().MQTT_BASE_TOPIC,
        device.farm_id,
        device.code,
        command=item.command,
    )
    bus = get_bus()
    bus.publish(
        topic,
        json.dumps({
            "correlation_id": item.correlation_id,
            "command": item.command,
            "payload": payload,
            "requires_ack": requires_ack,
            "timestamp": now.isoformat(),
        }),
        credentials=BusCredentials(username=device.code, password=""),
    )
    item.status = DeviceCommandStatus.sent if requires_ack else DeviceCommandStatus.acked
    if not requires_ack:
        item.acked_at = now
    db.commit()
    db.refresh(item)
    return item


def acknowledge_device_command(
    db: Session,
    device: Device,
    command_id: int,
    *,
    status: DeviceCommandStatus = DeviceCommandStatus.acked,
    message: str | None = None,
) -> DeviceCommand:
    item = (
        db.query(DeviceCommand)
        .filter(DeviceCommand.id == command_id, DeviceCommand.device_id == device.id)
        .first()
    )
    if item is None:
        raise NotFoundError(f"device command {command_id} not found")
    item.status = status
    item.acked_at = utcnow_naive()
    item.ack_message = message[:500] if message else None
    item.attempts = max(item.attempts, 1)
    db.commit()
    db.refresh(item)
    return item


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
