"""Phase 2 Module 9 — device registry: key lifecycle, auth independence,
RBAC (device.manage) and farm-ownership scoping."""

import hashlib


def _ts(minutes_ago: int = 0) -> str:
    from datetime import datetime, timedelta, timezone
    return (
        datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ).isoformat()


def _ingest_soil(client, key, readings):
    return client.post(
        "/api/v1/telemetry/soil",
        headers={"X-Device-Key": key},
        json={"readings": readings},
    )


# ---------------------------------------------------------------------------
# Registration + key material
# ---------------------------------------------------------------------------

def test_register_returns_plaintext_key_once_and_db_holds_only_digest(
    client, device_env, db
):
    key = device_env["soil_key"]
    assert key.startswith("dkey_") and len(key) > 30
    listed = client.get("/api/v1/devices", headers=device_env["headers"])
    assert listed.status_code == 200
    body = listed.text
    assert key not in body  # plaintext never re-served
    from app.models.iot import Device
    device = db.get(Device, device_env["soil"]["id"])
    assert device.key_hash == hashlib.sha256(key.encode()).hexdigest()
    assert key not in (device.key_hash, device.key_prefix)
    assert device.key_prefix == key[:13]


def test_register_requires_device_manage(client, make_user_with_role, auth_for,
                                         farm_payload, device_env):
    make_user_with_role("op@agrosmart.farmmail.org", "operator")
    r = client.post(
        "/api/v1/devices",
        headers=auth_for("op@agrosmart.farmmail.org"),
        json={"farm_id": device_env["farm_id"], "code": "X1", "name": "X1"},
    )
    assert r.status_code == 403  # operator lacks device.manage


def test_same_code_allowed_on_different_farm(
    client, register_user, auth_for, farm_payload, device_env
):
    register_user("other@agrosmart.farmmail.org")
    h2 = auth_for("other@agrosmart.farmmail.org")
    farm2 = client.post(
        "/api/v1/farms", headers=h2,
        json={**farm_payload, "code": "FARM2", "name": "Other Farm"},
    ).json()
    r = client.post(
        "/api/v1/devices", headers=h2,
        json={"farm_id": farm2["id"], "code": "PROBE-1", "name": "P1"},
    )
    assert r.status_code == 201  # uniqueness is per farm


def test_zone_from_other_farm_rejected(client, device_env, auth_for,
                                       register_user, farm_payload):
    register_user("z2@agrosmart.farmmail.org")
    h2 = auth_for("z2@agrosmart.farmmail.org")
    farm2 = client.post(
        "/api/v1/farms", headers=h2,
        json={**farm_payload, "code": "FARMZ", "name": "Z Farm"},
    ).json()
    zone = client.post(
        f"/api/v1/farms/{farm2['id']}/zones", headers=h2,
        json={"name": "Z", "code": "ZN1", "area_ha": "5"},
    ).json()
    r = client.post(
        "/api/v1/devices", headers=device_env["headers"],
        json={"farm_id": device_env["farm_id"], "code": "ZBAD",
              "name": "bad zone", "zone_id": zone["id"]},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Re-register / rotate / revoke
# ---------------------------------------------------------------------------

def test_reregister_rotates_key_and_old_key_stops_working(
    client, device_env
):
    old_key = device_env["soil_key"]
    r = client.post(
        "/api/v1/devices", headers=device_env["headers"],
        json={"farm_id": device_env["farm_id"], "code": "PROBE-1",
              "name": "Probe reflashed", "device_type": "soil_probe",
              "firmware_version": "2.0"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    new_key = body["api_key"]
    assert new_key != old_key
    assert body["device"]["id"] == device_env["soil"]["id"]  # same row
    assert body["device"]["firmware_version"] == "2.0"
    reading = [{"measured_at": _ts(), "moisture_pct": "30"}]
    assert _ingest_soil(client, old_key, reading).status_code == 401
    assert _ingest_soil(client, new_key, reading).status_code == 200


def test_rotate_key_endpoint(client, device_env):
    dev_id = device_env["soil"]["id"]
    r = client.post(f"/api/v1/devices/{dev_id}/rotate-key",
                    headers=device_env["headers"])
    assert r.status_code == 200
    new_key = r.json()["api_key"]
    assert new_key != device_env["soil_key"]
    assert _ingest_soil(
        client, new_key, [{"measured_at": _ts(), "moisture_pct": "31"}]
    ).status_code == 200
    assert _ingest_soil(
        client, device_env["soil_key"],
        [{"measured_at": _ts(5), "moisture_pct": "31"}],
    ).status_code == 401


def test_revoke_blocks_device_key_with_specific_message(client, device_env):
    dev_id = device_env["soil"]["id"]
    r = client.post(f"/api/v1/devices/{dev_id}/revoke",
                    headers=device_env["headers"])
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"
    blocked = _ingest_soil(
        client, device_env["soil_key"],
        [{"measured_at": _ts(), "moisture_pct": "20"}],
    )
    assert blocked.status_code == 401
    assert "revoked" in blocked.text.lower()


def test_reregister_reactivates_revoked_device(client, device_env):
    dev_id = device_env["soil"]["id"]
    client.post(f"/api/v1/devices/{dev_id}/revoke", headers=device_env["headers"])
    r = client.post(
        "/api/v1/devices", headers=device_env["headers"],
        json={"farm_id": device_env["farm_id"], "code": "PROBE-1",
              "name": "Back in service", "device_type": "soil_probe"},
    )
    assert r.status_code == 201
    assert r.json()["device"]["status"] == "active"
    assert _ingest_soil(
        client, r.json()["api_key"],
        [{"measured_at": _ts(), "moisture_pct": "22"}],
    ).status_code == 200


# ---------------------------------------------------------------------------
# Listing / status scoping
# ---------------------------------------------------------------------------

def test_other_managers_cannot_see_or_manage_devices(
    client, device_env, register_user, auth_for, farm_payload
):
    register_user("nosy@agrosmart.farmmail.org")
    h2 = auth_for("nosy@agrosmart.farmmail.org")
    dev_id = device_env["soil"]["id"]
    assert client.get(f"/api/v1/devices/{dev_id}", headers=h2).status_code == 404
    assert client.get("/api/v1/devices", headers=h2).json()["meta"]["total"] == 0
    assert client.post(f"/api/v1/devices/{dev_id}/revoke",
                       headers=h2).status_code == 404
    assert client.patch(f"/api/v1/devices/{dev_id}", headers=h2,
                        json={"name": "stolen"}).status_code == 404
    # farm_id filter on someone else's farm: 404, not 403
    assert client.get(f"/api/v1/devices?farm_id={device_env['farm_id']}",
                      headers=h2).status_code == 404


def test_admin_and_advisor_device_visibility(client, device_env, admin,
                                             make_user_with_role, auth_for):
    ha = auth_for(admin.email)
    assert client.get("/api/v1/devices", headers=ha).json()["meta"]["total"] == 2
    make_user_with_role("advd@agrosmart.farmmail.org", "advisor")
    # advisor has no device.manage -> 403 on the device registry
    assert client.get("/api/v1/devices",
                      headers=auth_for("advd@agrosmart.farmmail.org")
                      ).status_code == 403


def test_device_status_endpoint_reports_liveness(client, device_env):
    _ingest_soil(client, device_env["soil_key"],
                 [{"measured_at": _ts(), "moisture_pct": "33"}])
    r = client.get(f"/api/v1/devices/{device_env['soil']['id']}/status",
                   headers=device_env["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["is_stale"] is False
    assert body["last_seen_minutes_ago"] is not None
    assert body["open_faults"] == []


def test_status_reads_need_farm_access(client, device_env, make_user_with_role,
                                      auth_for):
    make_user_with_role("opst@agrosmart.farmmail.org", "operator")
    # operator lacks device.manage entirely:
    assert client.get(
        f"/api/v1/devices/{device_env['soil']['id']}/status",
        headers=auth_for("opst@agrosmart.farmmail.org"),
    ).status_code == 403


def test_missing_device_is_404(client, device_env):
    r = client.get("/api/v1/devices/999999", headers=device_env["headers"])
    assert r.status_code == 404
