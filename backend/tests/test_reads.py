"""Phase 2 — RBAC + farm-ownership scoping on the soil/weather read
endpoints, provenance flags in responses, and dynamic role edits gating
access (spec: every feature is permission-checked end to end)."""

from datetime import datetime, timedelta, timezone


def _ts(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _seed_soil(client, device_env, n=3):
    readings = [
        {"measured_at": _ts(30 - i * 10), "moisture_pct": str(25 + i),
         "simulated": i == 0}
        for i in range(n)
    ]
    r = client.post("/api/v1/telemetry/soil",
                    headers={"X-Device-Key": device_env["soil_key"]},
                    json={"readings": readings})
    assert r.status_code == 200, r.text
    return r


def _seed_weather(client, device_env):
    r = client.post(
        "/api/v1/telemetry/weather",
        headers={"X-Device-Key": device_env["wx_key"]},
        json={"readings": [{"measured_at": _ts(), "temperature_c": "25",
                            "humidity_pct": "60"}]},
    )
    assert r.status_code == 200, r.text


def test_soil_history_scoped_to_farm_owner(
    client, device_env, register_user, auth_for
):
    _seed_soil(client, device_env)
    register_user("roamgr@agrosmart.farmmail.org")
    h2 = auth_for("roamgr@agrosmart.farmmail.org")
    # own scope: nothing visible
    assert client.get("/api/v1/soil/history", headers=h2).json()["meta"]["total"] == 0
    # explicit filter on someone else's farm: 404, no enumeration
    assert client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}", headers=h2
    ).status_code == 404
    assert client.get(
        f"/api/v1/soil/latest?farm_id={device_env['farm_id']}", headers=h2
    ).status_code == 404
    # the owner sees all three
    assert client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"],
    ).json()["meta"]["total"] == 3


def test_advisor_and_admin_read_across_farms(client, device_env, admin,
                                             make_user_with_role, auth_for):
    _seed_soil(client, device_env)
    _seed_weather(client, device_env)
    make_user_with_role("advread@agrosmart.farmmail.org", "advisor")
    ha = auth_for("advread@agrosmart.farmmail.org")
    latest = client.get(f"/api/v1/soil/latest?farm_id={device_env['farm_id']}",
                        headers=ha).json()
    assert len(latest["items"]) == 1  # one row: newest per device
    newest = latest["items"][0]
    assert float(newest["moisture_pct"]) == 27.0  # newest seeded value
    wx_latest = client.get(f"/api/v1/weather/latest?farm_id={device_env['farm_id']}",
                           headers=ha).json()
    assert len(wx_latest["items"]) == 1
    adm = auth_for(admin.email)
    assert client.get("/api/v1/soil/history", headers=adm).json()["meta"]["total"] == 3
    assert client.get("/api/v1/weather/history",
                      headers=adm).json()["meta"]["total"] == 1


def test_provenance_flags_present_on_every_reading(client, device_env):
    _seed_soil(client, device_env)  # first (oldest) reading simulated
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"],
    ).json()["items"]
    assert {r["is_simulated"] for r in hist} == {True, False}
    for r in hist:
        assert "source" in r and isinstance(r["quality_flags"], list)


def test_history_time_window_and_device_filter(client, device_env):
    _seed_soil(client, device_env, n=3)
    _seed_weather(client, device_env)
    h = device_env["headers"]
    farm = device_env["farm_id"]
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)
    ).isoformat()  # naive UTC: '+' in an offset would mangle the query string
    recent = client.get(
        f"/api/v1/soil/history?farm_id={farm}&start={cutoff}", headers=h
    ).json()
    assert recent["meta"]["total"] == 1  # only _ts(0) reading is after cutoff
    per_dev = client.get(
        f"/api/v1/soil/history?farm_id={farm}&device_id={device_env['soil']['id']}",
        headers=h,
    ).json()
    assert per_dev["meta"]["total"] == 3
    wrong_dev = client.get(
        f"/api/v1/soil/history?farm_id={farm}&device_id={device_env['wx']['id']}",
        headers=h,
    ).json()
    assert wrong_dev["meta"]["total"] == 0


def test_forecasts_endpoint_returns_persisted_rows(
    client, device_env, register_user, auth_for
):
    # No provider run has happened yet in this test DB: a real, honest read
    # of an empty table (not a mock payload).
    resp = client.get(f"/api/v1/weather/forecasts?farm_id={device_env['farm_id']}",
                      headers=device_env["headers"])
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    # cross-owner farm filter is 404
    register_user("fcgr@agrosmart.farmmail.org")
    assert client.get(
        f"/api/v1/weather/forecasts?farm_id={device_env['farm_id']}",
        headers=auth_for("fcgr@agrosmart.farmmail.org"),
    ).status_code == 404


def test_manager_blocked_when_role_loses_read_permissions(
    client, device_env, admin, auth_for
):
    """RBAC is enforced dynamically from the DB role assignment: removing
    soil.read/weather.read from farm_manager closes those endpoints live
    for its own farm's data (ownership alone is not enough)."""
    _seed_soil(client, device_env)
    farm = device_env["farm_id"]
    hm = device_env["headers"]
    assert client.get(f"/api/v1/soil/latest?farm_id={farm}",
                      headers=hm).status_code == 200
    ha = auth_for(admin.email)
    stripped = ["farm.create", "farm.read.own", "farm.update.own",
                "farm.delete.own", "zone.create", "zone.read",
                "zone.update", "zone.delete", "audit.read"]
    r = client.patch("/api/v1/roles/farm_manager/permissions", headers=ha,
                     json={"permissions": stripped})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/soil/latest?farm_id={farm}",
                      headers=hm).status_code == 403
    assert client.get(f"/api/v1/soil/history?farm_id={farm}",
                      headers=hm).status_code == 403
    assert client.get(f"/api/v1/weather/latest?farm_id={farm}",
                      headers=hm).status_code == 403
    assert client.get(f"/api/v1/weather/history?farm_id={farm}",
                      headers=hm).status_code == 403
    assert client.get(f"/api/v1/weather/forecasts?farm_id={farm}",
                      headers=hm).status_code == 403
    assert client.get("/api/v1/faults", headers=hm).status_code == 403
    # device registry also gated (device.manage stripped)
    assert client.get("/api/v1/devices", headers=hm).status_code == 403
    # restore via the catalog default
    client.patch(
        "/api/v1/roles/farm_manager/permissions", headers=ha,
        json={"permissions": stripped + ["device.manage", "telemetry.ingest",
                                         "soil.read", "weather.read",
                                         "faults.read"]},
    )
    assert client.get(f"/api/v1/soil/latest?farm_id={farm}",
                      headers=hm).status_code == 200
