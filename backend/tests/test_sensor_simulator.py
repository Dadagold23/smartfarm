"""Phase 2 — sensor simulator tests: deterministic generator logic (pure)
plus one end-to-end seeded run piped through the real MQTT channel handler
(capture transport -> process_telemetry_message -> telemetry_service)."""

import json
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.iot.bus import BusCredentials
from app.iot.handler import process_telemetry_message
from app.iot.topics import build_topic
from scripts import sensor_simulator as sim

BASE = get_settings().MQTT_BASE_TOPIC
START = datetime(2026, 11, 6, 8, 0, 0)  # naive UTC, in the past for tests


def _cfg(**kw):
    base = dict(farm_id=1, soil_key="dkey_soil", scenario="normal",
                interval_s=60.0, duration_s=600.0, seed=42,
                simulate=True, start_time=START)
    base.update(kw)
    return sim.SimulatorConfig(**base)


def _seq(cfg, n=6):
    import random
    rng = random.Random(cfg.seed)
    return [sim.build_step(cfg, rng, i) for i in range(n)]


# ---------------------------------------------------------------------------
# Pure generator behaviour
# ---------------------------------------------------------------------------

def test_seeded_run_is_deterministic():
    a = _seq(_cfg())
    b = _seq(_cfg())
    assert json.dumps(a, default=str) == json.dumps(b, default=str)
    c = _seq(_cfg(seed=7))
    assert json.dumps(a, default=str) != json.dumps(c, default=str)


def test_normal_readings_are_plausible_and_flagged():
    steps = _seq(_cfg(), n=10)
    got = [s[0][0] for s in steps if s[0]]
    assert len(got) >= 6  # ~3% dropouts may skip a few
    for r in got:
        assert -50 < float(r["moisture_pct"]) < 150
        assert -100 < float(r["temperature_c"]) < 150
        assert r["simulated"] is True  # --simulate provenance stamp
    wx = [s[1][0] for s in steps if s[1]]
    assert not wx  # this cfg has no wx key


def test_weather_generator_bounds_and_shape():
    cfg = _cfg(soil_key=None, wx_key="dkey_wx")
    steps = _seq(cfg, n=8)
    wx = [s[1][0] for s in steps if s[1]]
    assert wx
    for r in wx:
        assert 0 <= float(r["humidity_pct"]) <= 100
        assert float(r["wind_speed_m_s"]) >= 0
        assert 0 <= float(r["wind_direction_deg"]) <= 360
        assert 0 <= float(r["solar_radiation_w_m2"]) <= 1361
        assert float(r["rainfall_mm"]) >= 0
        assert 850 <= float(r["pressure_hpa"]) <= 1100


def test_drift_scenario_walks_out_of_operating_range():
    steps = _seq(_cfg(scenario="drift"), n=8)
    moistures = [float(s[0][0]["moisture_pct"]) for s in steps if s[0]]
    assert moistures == sorted(moistures)          # creeping upward
    assert max(moistures) > 65.0                   # past the operating bound
    assert all(m < 150 for m in moistures)         # still within hard limits


def test_failure_scenario_is_flatline_plus_junk():
    steps = _seq(_cfg(scenario="failure"), n=6)
    got = [s[0][0] for s in steps if s[0]]
    assert {float(r["moisture_pct"]) for r in got} == {42.0}  # stuck value
    temps = {float(r["temperature_c"]) for r in got}
    assert temps and temps <= {95.0, -30.0}        # junk, inside hard limits


def test_stale_scenario_goes_silent_after_cutoff():
    cfg = _cfg(scenario="stale", interval_s=60.0, stale_after_s=120.0,
               dropout_probability=0.0)
    steps = _seq(cfg, n=6)
    spoken = [i for i, s in enumerate(steps) if s[0] is not None]
    # t=0 and t=60 speak; t>=120 silent
    assert spoken and max(spoken) <= 2
    assert len(spoken) < len(steps)


def test_without_simulate_flag_no_provenance_stamp():
    steps = _seq(_cfg(simulate=False), n=4)
    for s in steps:
        if s[0]:
            assert "simulated" not in s[0][0]


# ---------------------------------------------------------------------------
# End-to-end: seeded run -> MQTT channel handler -> pipeline -> faults
# ---------------------------------------------------------------------------

class _CaptureTransport:
    """Feeds each published batch through the real channel handler on the
    test session — exactly what the fallback bus subscriber does."""

    name = "capture"

    def __init__(self, db):
        self.db = db
        self.results = []

    def send(self, kind, key, code, farm_id, readings):
        topic = build_topic(BASE, farm_id, code, kind)
        res = process_telemetry_message(
            self.db, topic=topic,
            payload=json.dumps({"readings": readings}),
            credentials=BusCredentials(username=code, password=key),
            base_topic=BASE,
        )
        self.results.append(res)
        return res


def test_e2e_drift_run_flags_mqtt_simulated_and_raises_fault(
    client, db, device_env
):
    cfg = _cfg(farm_id=device_env["farm_id"], soil_key=device_env["soil_key"],
               soil_code=device_env["soil"]["code"],
               scenario="drift", seed=7, interval_s=60.0,
               start_time=datetime.now(timezone.utc).replace(tzinfo=None)
               - timedelta(minutes=30))
    t = _CaptureTransport(db)
    summary = sim.run(cfg, t, steps=8, sleep_fn=lambda _s: None,
                      verbose=False)
    assert summary["sent"]["soil"] > 0
    assert all(r["ok"] for r in t.results)
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"]).json()
    assert hist["meta"]["total"] == summary["sent"]["soil"]
    assert all(r["source"] == "mqtt" and r["is_simulated"] for r in hist["items"])
    faults = client.get(
        f"/api/v1/faults?farm_id={device_env['farm_id']}&open_only=true",
        headers=device_env["headers"]).json()
    assert "out_of_range" in {f["fault_type"] for f in faults["items"]}


def test_e2e_failure_run_triggers_flatline_fault(client, db, device_env):
    cfg = _cfg(farm_id=device_env["farm_id"], soil_key=device_env["soil_key"],
               soil_code=device_env["soil"]["code"],
               scenario="failure", seed=3, interval_s=60.0,
               simulate=False,
               start_time=datetime.now(timezone.utc).replace(tzinfo=None)
               - timedelta(minutes=20))
    t = _CaptureTransport(db)
    summary = sim.run(cfg, t, steps=5, sleep_fn=lambda _s: None,
                      verbose=False)
    assert summary["sent"]["soil"] >= 3
    faults = client.get(
        f"/api/v1/faults?farm_id={device_env['farm_id']}&open_only=true",
        headers=device_env["headers"]).json()
    types = {f["fault_type"] for f in faults["items"]}
    assert "flatline" in types and "out_of_range" in types
    # simulate flag off -> rows NOT flagged simulated (parity with real HW)
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"]).json()
    assert hist["meta"]["total"] == summary["sent"]["soil"]
    assert all(not r["is_simulated"] for r in hist["items"])
