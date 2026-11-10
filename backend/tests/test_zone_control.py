"""M8/M9 controller-backed irrigation controls and safety interlocks."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.schedule import IrrigationSchedule, ScheduleReason, ScheduleStatus


def _control_setup(client, register_user, auth_for, farm_payload, db):
    register_user("control@agrosmart.farmmail.org")
    headers = auth_for("control@agrosmart.farmmail.org")
    farm_resp = client.post("/api/v1/farms", headers=headers, json=farm_payload)
    assert farm_resp.status_code == 201, farm_resp.text
    farm_id = farm_resp.json()["id"]
    zone_resp = client.post(
        f"/api/v1/farms/{farm_id}/zones",
        headers=headers,
        json={
            "name": "Control Zone",
            "code": "CTRL-1",
            "area_ha": "5",
            "max_application_mm_per_hour": "8.0",
        },
    )
    assert zone_resp.status_code == 201, zone_resp.text
    zone_id = zone_resp.json()["id"]
    controller_resp = client.post(
        "/api/v1/devices",
        headers=headers,
        json={
            "farm_id": farm_id,
            "zone_id": zone_id,
            "code": "IRR-CTRL-1",
            "name": "Zone controller",
            "device_type": "irrigation_controller",
        },
    )
    assert controller_resp.status_code == 201, controller_resp.text
    controller = controller_resp.json()
    heartbeat = client.post(
        "/api/v1/devices/heartbeat",
        headers={"X-Device-Key": controller["api_key"]},
    )
    assert heartbeat.status_code == 200, heartbeat.text
    schedule = IrrigationSchedule(
        farm_id=farm_id,
        zone_id=zone_id,
        calculation_date=date.today(),
        target_date=date.today(),
        reference_et0_mm=Decimal("4.00"),
        crop_kc=Decimal("1.00"),
        crop_etc_mm=Decimal("4.00"),
        root_depth_m=Decimal("0.50"),
        total_available_water_mm=Decimal("100.00"),
        readily_available_water_mm=Decimal("50.00"),
        root_zone_depletion_mm=Decimal("55.00"),
        net_irrigation_requirement_mm=Decimal("5.00"),
        gross_irrigation_requirement_mm=Decimal("6.00"),
        recommended_runtime_minutes=30,
        recommended_volume_m3=Decimal("3.00"),
        status=ScheduleStatus.approved,
        reason=ScheduleReason.depletion_threshold_exceeded,
        safety_checks_passed=True,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return {
        "headers": headers,
        "farm_id": farm_id,
        "zone_id": zone_id,
        "controller_key": controller["api_key"],
        "schedule_id": schedule.id,
    }


def _request_control(client, setup, action, **data):
    return client.post(
        f"/api/v1/zones/{setup['zone_id']}/control",
        headers=setup["headers"],
        json={"action": action, **data},
    )


def _poll(client, setup):
    response = client.post(
        "/api/v1/devices/commands/pending",
        headers={"X-Device-Key": setup["controller_key"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _ack(client, setup, command_id, **payload):
    return client.post(
        f"/api/v1/devices/commands/{command_id}/ack",
        headers={"X-Device-Key": setup["controller_key"]},
        json=payload,
    )


def test_zone_only_runs_after_authenticated_controller_ack(
    client, register_user, auth_for, farm_payload, db
):
    setup = _control_setup(client, register_user, auth_for, farm_payload, db)

    start = _request_control(
        client,
        setup,
        "start",
        schedule_id=setup["schedule_id"],
    )
    assert start.status_code == 200, start.text
    assert start.json()["is_running"] is False
    assert start.json()["command_status"] == "queued"
    command_id = start.json()["command_id"]

    forged_ack = client.post(
        f"/api/v1/devices/commands/{command_id}/ack",
        headers=setup["headers"],
        json={"status": "acked", "observed_running": True, "interlocks_clear": True},
    )
    assert forged_ack.status_code == 401

    pending = _poll(client, setup)
    assert len(pending) == 1
    assert pending[0]["id"] == command_id
    assert pending[0]["control_action"] == "start"
    assert pending[0]["status"] == "sent"

    ack = _ack(
        client,
        setup,
        command_id,
        status="acked",
        observed_running=True,
        interlocks_clear=True,
        flow_lpm="12.5",
        pressure_bar="2.1",
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "acked"

    state = client.get(
        f"/api/v1/zones/{setup['zone_id']}/control",
        headers=setup["headers"],
    )
    assert state.status_code == 200
    assert state.json()["is_running"] is True
    assert float(state.json()["current_flow_lpm"]) == 12.5
    runtime = client.post(
        "/api/v1/devices/runtime",
        headers={"X-Device-Key": setup["controller_key"]},
        json={
            "zone_id": setup["zone_id"],
            "start_command_id": command_id,
            "is_running": False,
            "completed": True,
            "delivered_volume_m3": "2.75",
        },
    )
    assert runtime.status_code == 200, runtime.text
    assert runtime.json()["is_running"] is False
    assert float(runtime.json()["current_flow_lpm"]) == 12.5
    updated_schedule = db.get(IrrigationSchedule, setup["schedule_id"])
    db.refresh(updated_schedule)
    assert updated_schedule.status == ScheduleStatus.completed
    assert float(updated_schedule.actual_volume_m3) == 2.75


def test_bad_start_ack_latches_emergency_stop_and_blocks_restart(
    client, register_user, auth_for, farm_payload, db
):
    setup = _control_setup(client, register_user, auth_for, farm_payload, db)
    start = _request_control(
        client,
        setup,
        "start",
        schedule_id=setup["schedule_id"],
    )
    assert start.status_code == 200, start.text
    command_id = start.json()["command_id"]
    assert len(_poll(client, setup)) == 1

    ack = _ack(
        client,
        setup,
        command_id,
        status="acked",
        observed_running=False,
        interlocks_clear=True,
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "failed"

    state = client.get(
        f"/api/v1/zones/{setup['zone_id']}/control",
        headers=setup["headers"],
    ).json()
    assert state["is_running"] is False
    assert state["emergency_stop"] is True
    retry = _request_control(
        client,
        setup,
        "start",
        schedule_id=setup["schedule_id"],
    )
    assert retry.status_code == 400


def test_emergency_stop_clear_requires_controller_interlock_confirmation(
    client, register_user, auth_for, farm_payload, db
):
    setup = _control_setup(client, register_user, auth_for, farm_payload, db)
    estop = _request_control(client, setup, "emergency_stop")
    assert estop.status_code == 200, estop.text
    estop_command_id = estop.json()["command_id"]
    assert estop.json()["emergency_stop"] is True
    assert _poll(client, setup)[0]["id"] == estop_command_id
    estop_ack = _ack(
        client,
        setup,
        estop_command_id,
        status="acked",
        observed_running=False,
    )
    assert estop_ack.status_code == 200, estop_ack.text
    assert estop_ack.json()["status"] == "acked"

    clear = _request_control(client, setup, "clear_emergency_stop")
    assert clear.status_code == 200, clear.text
    clear_command_id = clear.json()["command_id"]
    assert _poll(client, setup)[0]["id"] == clear_command_id
    failed_clear = _ack(
        client,
        setup,
        clear_command_id,
        status="acked",
        observed_running=False,
        interlocks_clear=False,
    )
    assert failed_clear.status_code == 200, failed_clear.text
    assert failed_clear.json()["status"] == "failed"
    state = client.get(
        f"/api/v1/zones/{setup['zone_id']}/control",
        headers=setup["headers"],
    ).json()
    assert state["emergency_stop"] is True


def test_offline_emergency_stop_is_latched_and_queued_for_reconnect(
    client, register_user, auth_for, farm_payload, db
):
    setup = _control_setup(client, register_user, auth_for, farm_payload, db)
    from app.models.iot import Device

    controller = (
        db.query(Device)
        .filter(Device.code == "IRR-CTRL-1")
        .one()
    )
    controller.last_seen_at = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).replace(tzinfo=None)
    db.commit()

    response = _request_control(client, setup, "emergency_stop")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["emergency_stop"] is True
    assert body["command_status"] == "queued"
    assert "physical shutdown is unconfirmed" in body["control_message"]

    pending = _poll(client, setup)
    assert len(pending) == 1
    assert pending[0]["control_action"] == "emergency_stop"


def test_zone_runtime_cannot_be_forged_through_zone_update(
    client, register_user, auth_for, farm_payload
):
    register_user("runtime@agrosmart.farmmail.org")
    headers = auth_for("runtime@agrosmart.farmmail.org")
    farm = client.post("/api/v1/farms", headers=headers, json=farm_payload).json()
    zone = client.post(
        f"/api/v1/farms/{farm['id']}/zones",
        headers=headers,
        json={
            "name": "Protected Zone",
            "code": "PROTECTED",
            "area_ha": "5",
            "is_running": True,
        },
    )
    assert zone.status_code == 422
