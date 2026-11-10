"""M8/M9 zone control orchestration and command safety checks."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.permissions import satisfies
from app.models.farm import IrrigationZone, ZoneControlMode, ZoneStatus
from app.models.iot import Device, DeviceCommand, DeviceCommandStatus, DeviceStatus, DeviceType
from app.models.schedule import IrrigationSchedule, ScheduleStatus
from app.models.user import User
from app.services import audit_service, device_service, farm_service

ESTOP_ACTIONS = {"emergency_stop", "clear_emergency_stop"}


def _authorized_zone(
    db: Session, zone_id: int, user: User, held: set[str], action: str
) -> IrrigationZone:
    required = "estop.trigger" if action in ESTOP_ACTIONS else "valve.control"
    if not satisfies(required, held):
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError(f"missing permission {required}")
    zone = farm_service.get_zone(db, zone_id, user, held, "read")
    return db.execute(
        select(IrrigationZone)
        .where(IrrigationZone.id == zone.id)
        .with_for_update()
    ).scalar_one()


def _controller(db: Session, zone: IrrigationZone) -> Device | None:
    controllers = db.execute(
        select(Device).where(
            Device.farm_id == zone.farm_id,
            Device.zone_id == zone.id,
            Device.device_type == DeviceType.irrigation_controller,
            Device.status == DeviceStatus.active,
            Device.is_deleted.is_(False),
        )
    ).scalars().all()
    return controllers[0] if len(controllers) == 1 else None


def _controller_is_online(device: Device) -> bool:
    if device.last_seen_at is None:
        return False
    age_seconds = (device_service.utcnow_naive() - device.last_seen_at).total_seconds()
    stale_after = device_service.get_control_stale_seconds()
    return 0 <= age_seconds <= stale_after


def _active_control_command(db: Session, zone_id: int) -> DeviceCommand | None:
    return db.execute(
        select(DeviceCommand)
        .where(
            DeviceCommand.zone_id == zone_id,
            DeviceCommand.command == "zone_control",
            DeviceCommand.status.in_(
                [DeviceCommandStatus.queued, DeviceCommandStatus.sent]
            ),
        )
        .order_by(DeviceCommand.id.desc())
    ).scalars().first()


def set_zone_control(
    db: Session,
    zone_id: int,
    user: User,
    held: set[str],
    action: str,
    *,
    control_mode: ZoneControlMode | None = None,
    schedule_id: int | None = None,
    ip_address: str = "",
) -> tuple[IrrigationZone, DeviceCommand | None, str | None]:
    """Queue a gateway command; physical runtime changes only on device ack."""
    zone = _authorized_zone(db, zone_id, user, held, action)
    controller = _controller(db, zone)
    message: str | None = None

    if action == "start":
        if zone.is_running:
            raise BusinessRuleError("zone is already running")
        if zone.status != ZoneStatus.active:
            raise BusinessRuleError("only an active zone can start")
        if zone.emergency_stop:
            raise BusinessRuleError("zone cannot start while emergency stop is active")
        if zone.max_application_mm_per_hour is None:
            raise BusinessRuleError(
                "configure the zone application-rate safety cap before starting"
            )
        if controller is None:
            raise BusinessRuleError(
                "assign an active irrigation controller to this zone before starting"
            )
        if not _controller_is_online(controller):
            raise BusinessRuleError(
                "irrigation controller is offline; start command was not queued"
            )
        if schedule_id is None:
            raise BusinessRuleError("start requires an approved irrigation schedule")
        schedule = db.execute(
            select(IrrigationSchedule).where(
                IrrigationSchedule.id == schedule_id,
                IrrigationSchedule.farm_id == zone.farm_id,
                IrrigationSchedule.zone_id == zone.id,
            )
        ).scalar_one_or_none()
        if schedule is None:
            raise NotFoundError("approved irrigation schedule not found for this zone")
        if (
            schedule.status != ScheduleStatus.approved
            or not schedule.safety_checks_passed
            or schedule.weather_skip_flag
            or schedule.recommended_runtime_minutes <= 0
            or schedule.target_date != date.today()
        ):
            raise BusinessRuleError(
                "start requires a current, safety-checked, approved schedule with positive runtime"
            )
        if _active_control_command(db, zone.id) is not None:
            raise BusinessRuleError("another zone control command is still awaiting acknowledgement")
        payload = {
            "action": action,
            "zone_id": zone.id,
            "schedule_id": schedule.id,
            "runtime_minutes": schedule.recommended_runtime_minutes,
            "volume_m3": float(schedule.recommended_volume_m3),
            "max_application_mm_per_hour": float(zone.max_application_mm_per_hour),
            "control_mode": (control_mode or zone.control_mode).value,
        }
    elif action in {"stop", "emergency_stop", "clear_emergency_stop"}:
        if action == "clear_emergency_stop" and not zone.emergency_stop:
            raise BusinessRuleError("emergency stop is not active")
        if action == "clear_emergency_stop" and (
            controller is None or not _controller_is_online(controller)
        ):
            raise BusinessRuleError(
                "an online irrigation controller is required to verify local interlocks"
            )
        active = _active_control_command(db, zone.id)
        if active is not None and action == "clear_emergency_stop":
            raise BusinessRuleError(
                "another zone control command is still awaiting acknowledgement"
            )
        if action in {"stop", "emergency_stop"}:
            if action == "emergency_stop":
                zone.emergency_stop = True
            pending = db.execute(
                select(DeviceCommand).where(
                    DeviceCommand.zone_id == zone.id,
                    DeviceCommand.command == "zone_control",
                    DeviceCommand.control_action.notin_(["stop", "emergency_stop"]),
                    DeviceCommand.status == DeviceCommandStatus.queued,
                )
            ).scalars().all()
            for item in pending:
                item.status = DeviceCommandStatus.cancelled
        if action == "clear_emergency_stop":
            if zone.is_running:
                raise BusinessRuleError("stop the zone before clearing emergency stop")
        payload = {"action": action, "zone_id": zone.id}
    else:
        raise BusinessRuleError(f"unsupported control action '{action}'")

    if controller is None:
        if action in {"stop", "emergency_stop"}:
            message = (
                "No active irrigation controller is assigned; physical shutdown is unconfirmed."
            )
            audit_service.log(
                db,
                user_id=user.id,
                actor_label=user.email,
                action=f"zone.{action}.unconfirmed",
                resource_type="irrigation_zone",
                resource_id=zone.id,
                details={"farm_id": zone.farm_id},
                ip_address=ip_address,
            )
            db.commit()
            db.refresh(zone)
            return zone, None, message
        raise BusinessRuleError("assign an active irrigation controller to this zone")

    if action in {"stop", "emergency_stop"} and not _controller_is_online(controller):
        message = (
            f"{action.replace('_', ' ').capitalize()} command is queued, but the controller is offline; "
            "physical shutdown is unconfirmed."
        )

    command = device_service.enqueue_zone_control_command(
        db,
        controller,
        zone,
        action,
        payload,
        expires_at=(
            None
            if action in {"stop", "emergency_stop"}
            else device_service.utcnow_naive() + timedelta(minutes=5)
        ),
    )
    audit_service.log(
        db,
        user_id=user.id,
        actor_label=user.email,
        action=f"zone.{action}.queued",
        resource_type="irrigation_zone",
        resource_id=zone.id,
        details={
            "farm_id": zone.farm_id,
            "controller_id": controller.id,
            "command_id": command.id,
            "schedule_id": schedule_id,
        },
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(zone)
    db.refresh(command)
    return zone, command, message


def apply_control_ack(
    db: Session,
    command: DeviceCommand,
    *,
    succeeded: bool,
    observed_running: bool | None,
    interlocks_clear: bool | None,
    flow_lpm=None,
    pressure_bar=None,
    message: str | None = None,
) -> DeviceCommand:
    """Apply device-reported state only after validating the control result."""
    zone = db.get(IrrigationZone, command.zone_id) if command.zone_id else None
    action = command.control_action
    if zone is None or action is None:
        raise BusinessRuleError("control command is missing its zone/action binding")

    payload = json.loads(command.payload_json)
    expected_running = action == "start"
    if succeeded and observed_running is not expected_running:
        succeeded = False
        message = "controller acknowledgement did not confirm the requested running state"
    if succeeded and action == "clear_emergency_stop" and interlocks_clear is not True:
        succeeded = False
        message = "controller did not confirm that local safety interlocks are clear"
    if succeeded and action == "start" and interlocks_clear is not True:
        succeeded = False
        message = "controller did not confirm that local safety interlocks are clear"
    if succeeded and action == "start":
        schedule = db.get(IrrigationSchedule, payload.get("schedule_id"))
        if (
            zone.emergency_stop
            or zone.status != ZoneStatus.active
            or zone.max_application_mm_per_hour is None
            or Decimal(str(zone.max_application_mm_per_hour))
            != Decimal(str(payload.get("max_application_mm_per_hour")))
            or schedule is None
            or schedule.status != ScheduleStatus.approved
            or not schedule.safety_checks_passed
            or schedule.weather_skip_flag
            or schedule.target_date < date.today()
            or schedule.recommended_runtime_minutes != payload.get("runtime_minutes")
        ):
            succeeded = False
            message = "start interlocks changed before controller acknowledgement"
        newer_stop = db.execute(
            select(DeviceCommand.id).where(
                DeviceCommand.zone_id == zone.id,
                DeviceCommand.id > command.id,
                DeviceCommand.control_action.in_(["stop", "emergency_stop"]),
                DeviceCommand.status.in_(
                    [
                        DeviceCommandStatus.queued,
                        DeviceCommandStatus.sent,
                        DeviceCommandStatus.acked,
                    ]
                ),
            )
        ).first()
        if newer_stop is not None:
            succeeded = False
            message = "start was superseded by a later stop command"
    if succeeded and action == "clear_emergency_stop":
        newer_stop = db.execute(
            select(DeviceCommand.id).where(
                DeviceCommand.zone_id == zone.id,
                DeviceCommand.id > command.id,
                DeviceCommand.control_action == "emergency_stop",
                DeviceCommand.status.in_(
                    [
                        DeviceCommandStatus.queued,
                        DeviceCommandStatus.sent,
                        DeviceCommandStatus.acked,
                    ]
                ),
            )
        ).first()
        if newer_stop is not None:
            succeeded = False
            message = "emergency stop was reasserted after this clear command"

    command.status = (
        DeviceCommandStatus.acked if succeeded else DeviceCommandStatus.failed
    )
    command.acked_at = device_service.utcnow_naive()
    command.ack_message = message[:500] if message else None
    command.attempts = max(command.attempts, 1)

    if flow_lpm is not None:
        zone.current_flow_lpm = flow_lpm
    if pressure_bar is not None:
        zone.pressure_bar = pressure_bar

    if succeeded:
        if action == "start":
            zone.is_running = True
            zone.control_mode = ZoneControlMode(
                payload.get(
                    "control_mode", zone.control_mode.value
                )
            )
            zone.last_started_at = command.acked_at
            zone.last_stopped_at = None
            schedule = db.get(IrrigationSchedule, payload["schedule_id"])
            schedule.status = ScheduleStatus.executing
            schedule.actual_start_time = command.acked_at
        elif action in {"stop", "emergency_stop"}:
            zone.is_running = False
            zone.last_stopped_at = command.acked_at
            if action == "emergency_stop":
                zone.emergency_stop = True
            active_schedule = db.execute(
                select(IrrigationSchedule).where(
                    IrrigationSchedule.zone_id == zone.id,
                    IrrigationSchedule.status == ScheduleStatus.executing,
                )
            ).scalars().first()
            if active_schedule is not None:
                active_schedule.status = ScheduleStatus.cancelled
                active_schedule.actual_end_time = command.acked_at
        elif action == "clear_emergency_stop":
            zone.is_running = False
            zone.emergency_stop = False
    else:
        if observed_running is not None:
            zone.is_running = observed_running
            if observed_running:
                zone.last_started_at = command.acked_at
            else:
                zone.last_stopped_at = command.acked_at
        zone.emergency_stop = True
    audit_service.log(
        db,
        user_id=None,
        actor_label=f"device:{command.device.code}",
        action=f"zone.{action}.{'acked' if succeeded else 'failed'}",
        resource_type="irrigation_zone",
        resource_id=zone.id,
        details={
            "command_id": command.id,
            "observed_running": observed_running,
            "interlocks_clear": interlocks_clear,
            "message": message,
        },
    )
    db.commit()
    db.refresh(command)
    return command
