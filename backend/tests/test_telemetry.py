"""Phase 2 — telemetry ingestion endpoints: device-key vs user-JWT auth,
validation bounds, idempotent dedupe, batch handling, provenance flags."""

from datetime import datetime, timedelta, timezone


def _ts(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _ingest_soil(client, key, readings, headers=None):
    h = dict(headers or {})
    if key:
        h["X-Device-Key"] = key
    return client.post("/api/v1/telemetry/soil", headers=h,
                       json={"readings": readings})


def _one(client, key, moisture="30.5", minutes_ago=0, **extra):
    return _ingest_soil(client, key, [
        {"measured_at": _ts(minutes_ago), "moisture_pct": moisture, **extra}
    ])


# ---------------------------------------------------------------------------
# Device-key authentication (independent of user JWT)
# ---------------------------------------------------------------------------

def test_device_key_ingest_accepted_and_stored(client, device_env):
    r = _one(client, device_env["soil_key"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 1 and body["duplicates"] == 0
    assert body["device_id"] == device_env["soil"]["id"]
    assert body["results"][0]["status"] == "accepted"
    hist = client.get(f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
                      headers=device_env["headers"])
    assert hist.json()["meta"]["total"] == 1
    reading = hist.json()["items"][0]
    assert float(reading["moisture_pct"]) == 30.5
    assert reading["source"] == "device" and reading["is_simulated"] is False


def test_no_credentials_is_401(client, device_env):
    assert _one(client, None).status_code == 401


def test_wrong_device_key_is_401(client, device_env):
    assert _one(client, "dkey_totally-made-out-key-material").status_code == 401


def test_valid_user_jwt_without_device_header_works_with_device_id(
    client, device_env
):
    r = client.post(
        "/api/v1/telemetry/soil",
        headers=device_env["headers"],
        json={"device_id": device_env["soil"]["id"],
              "readings": [{"measured_at": _ts(), "moisture_pct": "28"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1


def test_user_jwt_without_telemetry_ingest_permission_is_403(
    client, device_env, make_user_with_role, auth_for, register_user
):
    # viewer holds soil.read but NOT telemetry.ingest
    make_user_with_role("viewt@agrosmart.farmmail.org", "viewer")
    r = client.post(
        "/api/v1/telemetry/soil",
        headers=auth_for("viewt@agrosmart.farmmail.org"),
        json={"device_id": device_env["soil"]["id"],
              "readings": [{"measured_at": _ts(), "moisture_pct": "28"}]},
    )
    assert r.status_code == 403
    # farm_manager without access to that farm: 404 (ownership hidden)
    register_user("mgrt@agrosmart.farmmail.org")
    r2 = client.post(
        "/api/v1/telemetry/soil",
        headers=auth_for("mgrt@agrosmart.farmmail.org"),
        json={"device_id": device_env["soil"]["id"],
              "readings": [{"measured_at": _ts(1), "moisture_pct": "28"}]},
    )
    assert r2.status_code == 404


def test_user_jwt_without_device_id_is_422(client, device_env):
    r = client.post(
        "/api/v1/telemetry/soil",
        headers=device_env["headers"],
        json={"readings": [{"measured_at": _ts(), "moisture_pct": "28"}]},
    )
    assert r.status_code == 422


def test_device_key_cannot_impersonate_another_device(client, device_env):
    r = client.post(
        "/api/v1/telemetry/soil",
        headers={"X-Device-Key": device_env["soil_key"]},
        json={"device_id": device_env["wx"]["id"],
              "readings": [{"measured_at": _ts(), "moisture_pct": "28"}]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# Validation: hard pydantic bounds (422) and per-item rejection
# ---------------------------------------------------------------------------

def test_hard_bound_rejects_nonsense_moisture(client, device_env):
    r = _one(client, device_env["soil_key"], moisture="400")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "request_validation_failed"


def test_missing_all_metrics_is_422(client, device_env):
    r = _ingest_soil(client, device_env["soil_key"],
                     [{"measured_at": _ts()}])
    assert r.status_code == 422


def test_future_timestamp_rejected_per_item(client, device_env):
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    r = _ingest_soil(client, device_env["soil_key"], [
        {"measured_at": future, "moisture_pct": "30"},
        {"measured_at": _ts(), "moisture_pct": "31"},
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["rejected"] == 1 and body["accepted"] == 1
    assert body["results"][0]["status"] == "rejected"
    assert "future" in body["results"][0]["error"]
    hist = client.get(f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
                      headers=device_env["headers"]).json()
    assert hist["meta"]["total"] == 1


# ---------------------------------------------------------------------------
# Dedupe (idempotency)
# ---------------------------------------------------------------------------

def test_replayed_message_is_duplicate_not_double_stored(client, device_env):
    ts = _ts(30)
    r1 = _ingest_soil(client, device_env["soil_key"],
                      [{"measured_at": ts, "moisture_pct": "30"}])
    r2 = _ingest_soil(client, device_env["soil_key"],
                      [{"measured_at": ts, "moisture_pct": "30"}])
    assert r1.json()["accepted"] == 1
    assert r2.json()["accepted"] == 0 and r2.json()["duplicates"] == 1
    assert r2.json()["results"][0]["status"] == "duplicate"
    assert r2.json()["results"][0]["reading_id"] == r1.json()["results"][0]["reading_id"]
    hist = client.get(f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
                      headers=device_env["headers"]).json()
    assert hist["meta"]["total"] == 1


def test_duplicate_within_single_batch(client, device_env):
    ts = _ts(5)
    r = _ingest_soil(client, device_env["soil_key"], [
        {"measured_at": ts, "moisture_pct": "30"},
        {"measured_at": ts, "moisture_pct": "30"},
        {"measured_at": _ts(4), "moisture_pct": "31"},
    ])
    body = r.json()
    assert body["accepted"] == 2 and body["duplicates"] == 1


# ---------------------------------------------------------------------------
# Liveness + provenance
# ---------------------------------------------------------------------------

def test_ingestion_updates_device_last_seen(client, device_env):
    before = client.get(f"/api/v1/devices/{device_env['soil']['id']}",
                        headers=device_env["headers"]).json()
    assert before["last_seen_at"] is None
    _one(client, device_env["soil_key"])
    after = client.get(f"/api/v1/devices/{device_env['soil']['id']}",
                       headers=device_env["headers"]).json()
    assert after["last_seen_at"] is not None


def test_duplicate_replay_still_advances_last_seen(client, device_env, db):
    from app.models.iot import Device
    _one(client, device_env["soil_key"], minutes_ago=10)
    db.expire_all()
    first_seen = db.get(Device, device_env["soil"]["id"]).last_seen_at
    # replay same measured_at: duplicate, but the device was heard from now
    _one(client, device_env["soil_key"], minutes_ago=10)
    db.expire_all()
    assert db.get(Device, device_env["soil"]["id"]).last_seen_at >= first_seen


def test_simulated_provenance_flag_persisted_and_returned(client, device_env):
    r = _one(client, device_env["soil_key"], simulated=True)
    assert r.json()["results"][0]["is_simulated"] is True
    hist = client.get(f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
                      headers=device_env["headers"]).json()
    assert hist["items"][0]["is_simulated"] is True


# ---------------------------------------------------------------------------
# Weather ingestion
# ---------------------------------------------------------------------------

def test_weather_ingest_full_station_payload(client, device_env):
    r = client.post(
        "/api/v1/telemetry/weather",
        headers={"X-Device-Key": device_env["wx_key"]},
        json={"readings": [{
            "measured_at": _ts(), "temperature_c": "24.5",
            "humidity_pct": "55", "wind_speed_m_s": "3.2",
            "wind_direction_deg": "180", "solar_radiation_w_m2": "610",
            "rainfall_mm": "0.0", "pressure_hpa": "1013.2",
        }]},
    )
    assert r.status_code == 200 and r.json()["accepted"] == 1
    latest = client.get(f"/api/v1/weather/latest?farm_id={device_env['farm_id']}",
                        headers=device_env["headers"]).json()
    assert len(latest["items"]) == 1
    obs = latest["items"][0]
    assert float(obs["temperature_c"]) == 24.5
    assert float(obs["solar_radiation_w_m2"]) == 610.0


def test_soil_and_weather_tables_are_separate(client, device_env):
    client.post("/api/v1/telemetry/weather",
                headers={"X-Device-Key": device_env["wx_key"]},
                json={"readings": [{"measured_at": _ts(), "temperature_c": "22"}]})
    soil_latest = client.get(f"/api/v1/soil/latest?farm_id={device_env['farm_id']}",
                             headers=device_env["headers"]).json()
    assert soil_latest["items"] == []


def test_empty_batch_is_422(client, device_env):
    r = _ingest_soil(client, device_env["soil_key"], [])
    assert r.status_code == 422
