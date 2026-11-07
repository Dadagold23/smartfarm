"""Phase 2 — sensor failure detection: STALE / OUT_OF_RANGE / FLATLINE.

Covers the fault lifecycle (create-once per device+type, resolve when the
condition clears), the stale scan behind GET /faults, RBAC (faults.read)
and farm-ownership scoping, plus audit trail entries.
"""

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.models.iot import Device


def _ts(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _ingest(client, key, readings):
    return client.post("/api/v1/telemetry/soil",
                       headers={"X-Device-Key": key},
                       json={"readings": readings})


def _open_faults(client, headers, device_id=None):
    url = "/api/v1/faults?open_only=true"
    if device_id:
        url += f"&device_id={device_id}"
    return client.get(url, headers=headers).json()["items"]


def _make_stale(db, device_env, hours=3):
    device = db.get(Device, device_env["soil"]["id"])
    device.last_seen_at = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    )
    db.commit()


def _flatline_series(count: int, value: str = "41.25"):
    """count readings spaced 10 minutes apart, oldest first, ending 10 min
    in the past so a following _ts(0) clear-up can never dedupe-collide."""
    return [
        {"measured_at": _ts((count - i) * 10), "moisture_pct": value}
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# STALE
# ---------------------------------------------------------------------------

def test_stale_device_gets_fault_via_scan(client, device_env, db):
    _ingest(client, device_env["soil_key"],
            [{"measured_at": _ts(60), "moisture_pct": "30"}])
    assert _open_faults(client, device_env["headers"]) == []
    _make_stale(db, device_env)
    faults = _open_faults(client, device_env["headers"])
    assert [f["fault_type"] for f in faults] == ["stale_data"]
    assert faults[0]["device_id"] == device_env["soil"]["id"]


def test_stale_fault_created_once_and_resolved_by_new_telemetry(
    client, device_env, db
):
    _ingest(client, device_env["soil_key"],
            [{"measured_at": _ts(60), "moisture_pct": "30"}])
    _make_stale(db, device_env)
    first = _open_faults(client, device_env["headers"])
    second = _open_faults(client, device_env["headers"])
    # create-once: repeated scans do not spam duplicate open events
    assert len(first) == 1 and len(second) == 1
    assert first[0]["id"] == second[0]["id"]

    # fresh telemetry clears the condition
    _ingest(client, device_env["soil_key"],
            [{"measured_at": _ts(1), "moisture_pct": "31"}])
    assert _open_faults(client, device_env["headers"]) == []
    every = client.get("/api/v1/faults?open_only=false",
                       headers=device_env["headers"]).json()["items"]
    stale = [f for f in every if f["fault_type"] == "stale_data"]
    assert len(stale) == 1 and stale[0]["resolved_at"] is not None


def test_revoked_devices_are_not_scanned_for_staleness(
    client, device_env, db
):
    dev_id = device_env["soil"]["id"]
    client.post(f"/api/v1/devices/{dev_id}/revoke", headers=device_env["headers"])
    _make_stale(db, device_env)
    assert _open_faults(client, device_env["headers"]) == []


# ---------------------------------------------------------------------------
# OUT_OF_RANGE
# ---------------------------------------------------------------------------

def test_out_of_range_reading_is_stored_flagged_and_faulted(
    client, device_env
):
    # timestamps must ascend so the "latest reading" re-evaluation sees
    # the clear-up last.
    r = _ingest(client, device_env["soil_key"],
                [{"measured_at": _ts(20), "moisture_pct": "80"}])
    body = r.json()
    assert body["accepted"] == 1  # evidence kept, not dropped
    assert "moisture_pct" in body["results"][0]["quality_flags"]
    faults = _open_faults(client, device_env["headers"])
    assert [f["fault_type"] for f in faults] == ["out_of_range"]
    assert "moisture_pct" in faults[0]["message"]

    r2 = _ingest(client, device_env["soil_key"],
                 [{"measured_at": _ts(10), "moisture_pct": "85"}])
    assert r2.json()["accepted"] == 1  # still stored
    open_now = _open_faults(client, device_env["headers"])
    assert len(open_now) == 1  # same single open event, refreshed

    r3 = _ingest(client, device_env["soil_key"],
                 [{"measured_at": _ts(), "moisture_pct": "40"}])
    assert "moisture_pct" not in r3.json()["results"][0]["quality_flags"]
    assert _open_faults(client, device_env["headers"]) == []


def test_out_of_range_operating_override_applies(client, device_env,
                                                 monkeypatch):
    # A deployment whose probe tolerates up to 90% VWC sees no fault.
    monkeypatch.setattr(get_settings(), "TELEMETRY_OPERATING_RANGES",
                        {"soil.moisture_pct": [0.0, 90.0]})
    r = _ingest(client, device_env["soil_key"],
                [{"measured_at": _ts(), "moisture_pct": "80"}])
    assert r.json()["results"][0]["quality_flags"] == []
    assert _open_faults(client, device_env["headers"]) == []


def test_weather_out_of_range_wind(client, device_env):
    r = client.post(
        "/api/v1/telemetry/weather",
        headers={"X-Device-Key": device_env["wx_key"]},
        json={"readings": [{"measured_at": _ts(), "wind_speed_m_s": "90"}]},
    )
    assert r.status_code == 200 and r.json()["accepted"] == 1
    url = f"/api/v1/faults?open_only=true&farm_id={device_env['farm_id']}"
    faults = client.get(url, headers=device_env["headers"]).json()["items"]
    assert [f["fault_type"] for f in faults] == ["out_of_range"]
    assert faults[0]["device_id"] == device_env["wx"]["id"]


# ---------------------------------------------------------------------------
# FLATLINE
# ---------------------------------------------------------------------------

def test_flatline_raises_after_n_identical_and_resolves_on_change(
    client, device_env
):
    n = get_settings().FLATLINE_CONSECUTIVE_READINGS
    series = _flatline_series(n)
    for i, reading in enumerate(series[:-1]):
        r = _ingest(client, device_env["soil_key"], [reading])
        assert r.json()["accepted"] == 1
        assert "flatline" not in r.json()["results"][0]["quality_flags"], (
            f"flatline must not fire after only {i + 1} readings"
        )
    assert _open_faults(client, device_env["headers"]) == []

    r = _ingest(client, device_env["soil_key"], [series[-1]])
    assert "flatline" in r.json()["results"][0]["quality_flags"]
    faults = _open_faults(client, device_env["headers"])
    assert [f["fault_type"] for f in faults] == ["flatline"]
    assert "moisture_pct" in faults[0]["message"]

    # a changed value clears the stuck-sensor suspicion
    _ingest(client, device_env["soil_key"],
            [{"measured_at": _ts(0), "moisture_pct": "39.5"}])
    assert _open_faults(client, device_env["headers"]) == []


def test_flatline_not_triggered_by_non_consecutive_repeat(client, device_env):
    # two matching values separated by a different one is not a run of N
    seq = [
        {"measured_at": _ts(20), "moisture_pct": "41.25"},
        {"measured_at": _ts(10), "moisture_pct": "20.0"},
        {"measured_at": _ts(0), "moisture_pct": "41.25"},
    ]
    for reading in seq:
        r = _ingest(client, device_env["soil_key"], [reading])
        assert r.json()["accepted"] == 1
    assert _open_faults(client, device_env["headers"]) == []


# ---------------------------------------------------------------------------
# RBAC + ownership scoping on GET /faults
# ---------------------------------------------------------------------------

def test_faults_requires_faults_read_permission(
    client, device_env, make_user_with_role, auth_for
):
    _ingest(client, device_env["soil_key"],
            [{"measured_at": _ts(), "moisture_pct": "80"}])  # open fault
    make_user_with_role("viewf@agrosmart.farmmail.org", "viewer")
    # viewer has no faults.read
    resp = client.get("/api/v1/faults",
                      headers=auth_for("viewf@agrosmart.farmmail.org"))
    assert resp.status_code == 403
    # operator HAS faults.read but only own-farm scope (operator owns none)
    make_user_with_role("opf@agrosmart.farmmail.org", "operator")
    resp2 = client.get("/api/v1/faults",
                       headers=auth_for("opf@agrosmart.farmmail.org"))
    assert resp2.status_code == 200
    assert resp2.json()["meta"]["total"] == 0
    # ... and cannot filter by someone else's farm (404, no enumeration)
    resp3 = client.get(
        f"/api/v1/faults?farm_id={device_env['farm_id']}",
        headers=auth_for("opf@agrosmart.farmmail.org"),
    )
    assert resp3.status_code == 404


def test_advisor_and_admin_see_other_farms_faults(
    client, device_env, make_user_with_role, auth_for, admin
):
    _ingest(client, device_env["soil_key"],
            [{"measured_at": _ts(), "moisture_pct": "80"}])  # open fault
    make_user_with_role("advf@agrosmart.farmmail.org", "advisor")
    resp = client.get("/api/v1/faults",
                      headers=auth_for("advf@agrosmart.farmmail.org"))
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 1
    resp_admin = client.get("/api/v1/faults", headers=auth_for(admin.email))
    assert resp_admin.json()["meta"]["total"] == 1


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def test_fault_and_ingest_activity_are_audited(client, device_env, admin,
                                               auth_for):
    _ingest(client, device_env["soil_key"],
            [{"measured_at": _ts(), "moisture_pct": "80"}])
    client.get("/api/v1/faults", headers=device_env["headers"])  # scan runs
    ha = auth_for(admin.email)
    actions = {
        item["action"]
        for item in client.get("/api/v1/audit-logs?limit=200",
                               headers=ha).json()["items"]
    }
    assert {"device.register", "telemetry.ingest.soil", "fault.detected"} <= actions
    ingest_entry = client.get(
        "/api/v1/audit-logs?action=telemetry.ingest.soil", headers=ha
    ).json()["items"][0]
    assert ingest_entry["actor_label"].startswith("device:")
