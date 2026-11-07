"""Throwaway Phase 2 end-to-end smoke check.

Runs against a temporary SQLite DB served on :8001 so the dev database is
untouched. Exercises the exact calls the new UI pages make.
"""

import httpx

BASE = "http://127.0.0.1:8001"
API = f"{BASE}/api/v1"
EMAIL = "smoke@agrosmart.farmmail.org"
PASSWORD = "SmokeTest-2026!"

failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {extra}" if extra else ""))
    if not cond:
        failures.append(name)


with httpx.Client(timeout=30) as c:
    r = c.post(f"{API}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "Smoke Manager"})
    check("register", r.status_code == 201, r.text[:200])
    r = c.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    check("login", r.status_code == 200, r.text[:200])
    tok = r.json()["tokens"]["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"

    r = c.post(f"{API}/farms", json={
        "name": "Smoke Farm", "code": "SMK-1", "latitude": 9.9,
        "longitude": -1.2, "water_source": "borehole"})
    check("create farm", r.status_code in (200, 201), r.text[:200])
    farm_id = r.json()["id"]

    r = c.post(f"{API}/farms/{farm_id}/zones",
               json={"name": "Zone A", "code": "ZN-1", "sequence_number": 1})
    check("create zone", r.status_code in (200, 201), r.text[:200])
    zone_id = r.json()["id"] if r.status_code in (200, 201) else None

    # --- /devices page: register, list, status, rotate, revoke ---
    soil_key = wx_key = None
    for code, dtype in [("SP-SMOKE-1", "soil_probe"), ("WX-SMOKE-1", "weather_station")]:
        r = c.post(f"{API}/devices", json={
            "farm_id": farm_id, "zone_id": zone_id, "name": f"Sim {dtype}",
            "code": code, "device_type": dtype, "model": "esp32-sim"})
        check(f"register device {code}", r.status_code == 201, r.text[:200])
        body = r.json()
        key = body.get("api_key")
        check("device key returned once", bool(key) and key.startswith("dkey_"), str(key)[:12])
        if dtype == "soil_probe":
            soil_key, soil_id = key, body["device"]["id"]
        else:
            wx_key, wx_id = key, body["device"]["id"]

    r = c.get(f"{API}/devices")
    check("list devices", r.status_code == 200 and r.json()["meta"]["total"] == 2, r.text[:200])

    # --- ingestion via device key (what the simulator does) ---
    dev = httpx.Client(timeout=30)
    r = dev.post(f"{API}/telemetry/soil", headers={"X-Device-Key": soil_key}, json={
        "readings": [{"measured_at": "2026-11-06T12:00:00Z", "moisture_pct": 28.5,
                      "temperature_c": 31.2, "ec_mS_cm": 0.9, "probe_depth_cm": 30,
                      "simulated": True}]})
    check("soil ingest (device key)", r.status_code == 200, r.text[:300])
    meta = r.json()
    check("soil accepted", meta["results"][0]["status"] == "accepted",
          str(meta["results"][0]))

    r = dev.post(f"{API}/telemetry/soil", headers={"X-Device-Key": soil_key}, json={
        "readings": [{"measured_at": "2026-11-06T12:00:00Z", "moisture_pct": 28.5}]})
    check("replay deduped", r.json()["results"][0]["status"] == "duplicate",
          str(r.json()["results"][0]))

    r = dev.post(f"{API}/telemetry/weather", headers={"X-Device-Key": wx_key}, json={
        "readings": [{"measured_at": "2026-11-06T12:00:00Z", "temperature_c": 33.0,
                      "humidity_pct": 41.0, "wind_speed_m_s": 3.1,
                      "solar_radiation_w_m2": 780.0, "rainfall_mm": 0.0,
                      "pressure_hpa": 1009.0, "simulated": True}]})
    check("weather ingest", r.status_code == 200
          and r.json()["results"][0]["status"] == "accepted", r.text[:300])

    # out-of-range reading -> fault engine + quality flag
    r = dev.post(f"{API}/telemetry/soil", headers={"X-Device-Key": soil_key}, json={
        "readings": [{"measured_at": "2026-11-06T12:05:00Z", "moisture_pct": 140.0}]})
    res = r.json()["results"][0]
    check("out-of-range flagged", "out_of_range" in res["quality_flags"], str(res))
    check("out-of-range fault raised",
          any(f["fault_type"] == "out_of_range" for f in res["faults"]), str(res["faults"])[:200])

    r = dev.post(f"{API}/telemetry/soil", headers={"X-Device-Key": "dkey_nope"}, json={
        "readings": [{"measured_at": "2026-11-06T12:10:00Z", "moisture_pct": 20.0}]})
    check("bad device key rejected 401", r.status_code == 401, r.text[:150])

    # --- /sensor-data page reads ---
    r = c.get(f"{API}/soil/latest")
    items = r.json()["items"]
    check("soil latest", r.status_code == 200 and len(items) >= 1, r.text[:200])
    check("provenance badged", items and items[0]["is_simulated"] is True
          and "source" in items[0] and isinstance(items[0]["quality_flags"], list),
          str(items[:1]))

    r = c.get(f"{API}/weather/latest")
    check("weather latest", r.status_code == 200 and len(r.json()["items"]) == 1, r.text[:200])

    r = c.get(f"{API}/soil/history", params={"farm_id": farm_id, "limit": 10})
    check("soil history", r.status_code == 200 and r.json()["meta"]["total"] >= 2, r.text[:200])

    # --- forecasts ---
    r = c.get(f"{API}/weather/forecast-providers")
    provs = {p["id"]: p for p in r.json()["items"]}
    check("provider registry", {"simulated", "open_meteo"} <= set(provs), str(provs)[:250])

    r = c.post(f"{API}/weather/forecast-refresh",
               json={"farm_id": farm_id, "days": 3, "provider": "simulated"})
    check("forecast refresh (simulated)", r.status_code == 200, r.text[:250])
    fr = r.json()
    check("simulated forecast badged", fr["is_simulated"] is True
          and fr["provider"] == "simulated" and len(fr["items"]) == 3, str(fr)[:250])

    r = c.post(f"{API}/weather/forecast-refresh",
               json={"farm_id": farm_id, "days": 3, "provider": "open_meteo"})
    check("forecast refresh (live open_meteo)", r.status_code == 200, r.text[:250])
    if r.status_code == 200:
        live = r.json()
        row = live["items"][0]
        check("live forecast real + unbadged", live["is_simulated"] is False
              and row["temp_max_c"] is not None, str(row)[:250])

    r = c.post(f"{API}/weather/forecast-refresh",
               json={"farm_id": farm_id, "days": 2, "provider": "open_weather_map"})
    check("unconfigured provider fails loudly",
          r.status_code == 502 and "weather_provider_error" in r.text, r.text[:200])

    r = c.get(f"{API}/weather/forecasts", params={"farm_id": farm_id})
    check("forecasts read back", r.status_code == 200 and r.json()["meta"]["total"] >= 3,
          r.text[:200])

    # --- /faults page ---
    r = c.get(f"{API}/faults")
    check("faults listed", r.status_code == 200 and r.json()["meta"]["total"] >= 1, r.text[:300])
    types = {f["fault_type"] for f in r.json()["items"]}
    check("stale sweep ran without error", isinstance(types, set), str(types))

    # --- device status + rotate + revoke ---
    r = c.get(f"{API}/devices/{soil_id}/status")
    st = r.json()
    check("device status", r.status_code == 200 and st["device"]["id"] == soil_id
          and st["last_seen_minutes_ago"] is not None, str(st)[:250])

    r = c.post(f"{API}/devices/{soil_id}/rotate-key")
    new_key = r.json().get("api_key")
    check("rotate returns new key", bool(new_key), str(new_key)[:12])
    r = dev.post(f"{API}/telemetry/soil", headers={"X-Device-Key": soil_key}, json={
        "readings": [{"measured_at": "2026-11-06T13:00:00Z", "moisture_pct": 22.0}]})
    check("old key dead after rotate", r.status_code == 401, r.text[:150])

    r = c.post(f"{API}/devices/{wx_id}/revoke")
    check("revoke", r.status_code == 200 and r.json()["status"] == "revoked", r.text[:200])
    r = dev.post(f"{API}/telemetry/weather", headers={"X-Device-Key": wx_key}, json={
        "readings": [{"measured_at": "2026-11-06T13:05:00Z", "temperature_c": 30.0}]})
    check("revoked device rejected", r.status_code in (401, 403), r.text[:150])

print("\n" + ("ALL CHECKS PASSED" if not failures else f"FAILURES: {failures}"))
