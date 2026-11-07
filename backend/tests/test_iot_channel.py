"""Phase 2 Module 9 — MQTT device channel tests.

Covers the topic schema, the in-process fallback bus end-to-end (publish ->
shared handler -> telemetry_service -> read APIs), provenance
(source='mqtt'), cross-device topic authorization, payload validation, and
equivalence of dedupe/fault behaviour with the HTTP ingestion path.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.iot.bus import BusCredentials, InProcessMessageBus, get_bus
from app.iot.handler import process_telemetry_message
from app.iot.topics import (
    TopicError,
    build_topic,
    parse_topic,
    subscription_wildcard,
    topic_matches,
)
from app.core.config import get_settings

BASE = get_settings().MQTT_BASE_TOPIC


def _ts(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


# ---------------------------------------------------------------------------
# Topic schema (pure)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("farm_id,code,kind", [
    (7, "PROBE-1", "soil"),
    (1, "a", "weather"),
    (999999, "dev_02-x", "soil"),
])
def test_topic_roundtrip(farm_id, code, kind):
    topic = build_topic(BASE, farm_id, code, kind)
    parsed = parse_topic(topic, BASE)
    assert (parsed.farm_id, parsed.device_code, parsed.kind) == (farm_id, code, kind)


@pytest.mark.parametrize("bad", [
    "asiis/v1/7/PROBE-1/telemetry",              # too few segments
    "asiis/v1/7/PROBE-1/telemetry/soil/extra",   # too many
    "otherbase/v1/7/PROBE-1/telemetry/soil",     # wrong base
    "asiis/v1/0/PROBE-1/telemetry/soil",         # farm_id 0
    "asiis/v1/-3/PROBE-1/telemetry/soil",        # negative farm_id
    "asiis/v1/7/PROBE 1/telemetry/soil",         # space in code
    "asiis/v1/7/PROBE-1/telemetery/soil",        # typo literal segment
    "asiis/v1/7/PROBE-1/telemetry/gas",          # unknown kind
    "asiis/v1/+/PROBE-1/telemetry/soil",         # wildcard not a publish topic
    "asiis/v1/7/#",                              # subscription filter
    "",                                          # empty
    "  asiis/v1/7/PROBE-1/telemetry/soil",       # leading whitespace
])
def test_topic_rejected(bad):
    with pytest.raises(TopicError):
        parse_topic(bad, BASE)


def test_wildcard_matching():
    flt = subscription_wildcard(BASE)
    assert flt == "asiis/v1/+/+/telemetry/+"
    assert topic_matches(flt, "asiis/v1/7/P1/telemetry/soil")
    # '+' matches ANY single level (correct MQTT semantics): a wrong-kind
    # message still reaches the subscriber, which rejects it as invalid_topic.
    assert topic_matches(flt, "asiis/v1/7/P1/telemetry/gas")
    assert not topic_matches(flt, "asiis/v1/7/P1/cmd/soil")
    assert topic_matches("asiis/v1/7/#", "asiis/v1/7/P1/telemetry/soil")
    assert not topic_matches("asiis/v1/7/#", "asiis/v1/8/P1/telemetry/soil")
    assert topic_matches("asiis/v1/7/P1/telemetry/soil",
                         "asiis/v1/7/P1/telemetry/soil")


# ---------------------------------------------------------------------------
# In-process bus mechanics (pure)
# ---------------------------------------------------------------------------

def test_bus_fanout_and_credential_passthrough():
    bus = InProcessMessageBus()
    seen = []
    bus.subscribe("asiis/v1/+/+/telemetry/+",
                  lambda m: seen.append((m.topic, m.credentials.password)))
    creds = BusCredentials(username="P1", password="dkey_secret")
    n = bus.publish("asiis/v1/7/P1/telemetry/soil", b"{}", credentials=creds)
    assert n == 1 and seen == [("asiis/v1/7/P1/telemetry/soil", "dkey_secret")]
    assert bus.publish("asiis/v1/7/P1/cmd/soil", "{}") == 0  # no match


def test_bus_contains_faulty_subscriber():
    bus = InProcessMessageBus()

    def boom(_m):
        raise RuntimeError("consumer down")

    got = []
    bus.subscribe("asiis/v1/#", boom)
    bus.subscribe("asiis/v1/#", lambda m: got.append(m.topic))
    assert bus.publish("asiis/v1/7/P1/telemetry/soil", "{}") == 1  # boom failed
    assert len(got) == 1  # healthy consumer still delivered


# ---------------------------------------------------------------------------
# Handler unit behaviour (direct call, no bus)
# ---------------------------------------------------------------------------

def _handle(db, *, topic, payload, key, farm_id):
    return process_telemetry_message(
        db, topic=topic, payload=payload,
        credentials=BusCredentials(username="x", password=key),
        base_topic=BASE,
    )


def test_handler_rejects_malformed_topic(db, device_env):
    r = _handle(db, topic=f"bogus/{device_env['farm_id']}/PROBE-1/telemetry/soil",
                payload=b"{}", key=device_env["soil_key"],
                farm_id=device_env["farm_id"])
    assert r["ok"] is False and r["status"] == "invalid_topic"


def test_handler_rejects_bad_key(db, device_env):
    topic = build_topic(BASE, device_env["farm_id"], "PROBE-1", "soil")
    r = _handle(db, topic=topic, payload=b"{}", key="dkey_wrong",
                farm_id=device_env["farm_id"])
    assert r["ok"] is False and r["status"] == "auth_failed"


def test_handler_rejects_cross_device_topic(db, device_env):
    """Soil key publishing into the weather device's topic -> refused, and
    the victim device gets an audited auth_failure fault (via /faults)."""
    topic = build_topic(BASE, device_env["farm_id"], "WX-1", "weather")
    r = _handle(db, topic=topic,
                payload=json.dumps({"measured_at": _ts(), "temperature_c": "25"}),
                key=device_env["soil_key"], farm_id=device_env["farm_id"])
    assert r["ok"] is False and r["status"] == "topic_not_authorized"
    from app.models.weather import WeatherObservation
    assert db.query(WeatherObservation).count() == 0


# ---------------------------------------------------------------------------
# Bus end-to-end through the running app (lifespan registers subscriber)
# ---------------------------------------------------------------------------

@pytest.fixture()
def bus(client):
    """The app's fallback bus — client fixture keeps the lifespan alive so
    the telemetry subscription from app.main is registered."""
    return get_bus()


def _publish(client, bus, device_env, code, key, kind, readings,
             use_key=True):
    topic = build_topic(BASE, device_env["farm_id"], code, kind)
    payload = json.dumps(readings)
    creds = BusCredentials(username=code, password=key) if use_key else None
    assert bus.publish(topic, payload, credentials=creds) == 1
    return topic


def test_bus_publish_ingests_with_mqtt_source(client, bus, device_env):
    _publish(client, bus, device_env, "PROBE-1", device_env["soil_key"],
             "soil", {"measured_at": _ts(), "moisture_pct": "31.5",
                      "temperature_c": "22.4", "simulated": True})
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    items = hist.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["source"] == "mqtt"          # provenance hook works
    assert row["is_simulated"] is True      # simulator flag survives channel
    assert float(row["moisture_pct"]) == 31.5


def test_bus_weather_publish_and_dedupe_matches_http(client, bus, device_env):
    reading = {"measured_at": _ts(5), "temperature_c": "27.1",
               "humidity_pct": "55"}
    _publish(client, bus, device_env, "WX-1", device_env["wx_key"],
             "weather", reading)
    # exact replay over the bus -> duplicate (idempotent)
    _publish(client, bus, device_env, "WX-1", device_env["wx_key"],
             "weather", reading)
    hist = client.get(
        f"/api/v1/weather/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert hist.json()["meta"]["total"] == 1
    # same payload via HTTP for the same device+timestamp -> duplicate too:
    # dedupe is shared across transports, proving pipeline equivalence
    r = client.post("/api/v1/telemetry/weather",
                    headers={"X-Device-Key": device_env["wx_key"]},
                    json={"readings": [reading]})
    body = r.json()
    assert body["accepted"] == 0 and body["duplicates"] == 1


def test_bus_batch_list_payload(client, bus, device_env):
    readings = [{"measured_at": _ts(30 - i), "moisture_pct": "30",
                 "temperature_c": "20", "probe_depth_cm": "20"}
                for i in range(3)]
    _publish(client, bus, device_env, "PROBE-1", device_env["soil_key"],
             "soil", {"readings": readings})
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert hist.json()["meta"]["total"] == 3


def test_bus_fault_engine_active_on_mqtt_path(client, bus, device_env):
    """Flatline + out-of-range detection must fire over MQTT exactly as
    over HTTP (identical pipeline)."""
    topic = build_topic(BASE, device_env["farm_id"], "PROBE-1", "soil")
    for i in range(3):  # 3 identical moisture values -> flatline
        bus.publish(topic, json.dumps(
            {"measured_at": _ts(20 - i * 5), "moisture_pct": "40.0"}),
            credentials=BusCredentials(password=device_env["soil_key"]))
    faults = client.get(
        f"/api/v1/faults?farm_id={device_env['farm_id']}&open_only=true",
        headers=device_env["headers"])
    types = {f["fault_type"] for f in faults.json()["items"]}
    assert "flatline" in types
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert all(r["source"] == "mqtt" for r in hist.json()["items"])


def test_bus_rejects_cross_device_topic_end_to_end(client, bus, device_env):
    """Device A's key on device B's topic: nothing stored for B, and B
    carries an open auth_failure fault."""
    topic = build_topic(BASE, device_env["farm_id"], "WX-1", "weather")
    bus.publish(topic, json.dumps(
        {"measured_at": _ts(), "temperature_c": "25"}),
        credentials=BusCredentials(password=device_env["soil_key"]))
    hist = client.get(
        f"/api/v1/weather/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert hist.json()["meta"]["total"] == 0
    faults = client.get(
        f"/api/v1/faults?farm_id={device_env['farm_id']}&open_only=true",
        headers=device_env["headers"])
    af = [f for f in faults.json()["items"] if f["fault_type"] == "auth_failure"]
    assert af and af[0]["device_id"] == device_env["wx"]["id"]
    # A legitimate message from the rightful owner resolves it
    _publish(client, bus, device_env, "WX-1", device_env["wx_key"],
             "weather", {"measured_at": _ts(), "temperature_c": "26"})
    faults2 = client.get(
        f"/api/v1/faults?farm_id={device_env['farm_id']}&open_only=true",
        headers=device_env["headers"])
    assert not [f for f in faults2.json()["items"]
                if f["fault_type"] == "auth_failure"]


def test_bus_rejects_invalid_payloads(client, bus, device_env):
    topic = build_topic(BASE, device_env["farm_id"], "PROBE-1", "soil")
    creds = BusCredentials(password=device_env["soil_key"])
    assert bus.publish(topic, b"not json at all", credentials=creds) == 1
    # soil metrics on the WEATHER topic: schema is chosen by topic kind
    wtopic = build_topic(BASE, device_env["farm_id"], "WX-1", "weather")
    bus.publish(wtopic, json.dumps({"measured_at": _ts(),
                                    "moisture_pct": "30"}),
                credentials=BusCredentials(password=device_env["wx_key"]))
    # no metric at all
    bus.publish(topic, json.dumps({"measured_at": _ts()}), credentials=creds)
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    wx = client.get(
        f"/api/v1/weather/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert hist.json()["meta"]["total"] == 0
    assert wx.json()["meta"]["total"] == 0


def test_payload_device_key_defence_in_depth(client, bus, device_env):
    """Real-broker mode: the broker account may lack per-message identity,
    so an optional top-level payload device_key is honoured and must match
    the topic."""
    topic = build_topic(BASE, device_env["farm_id"], "PROBE-1", "soil")
    bus.publish(topic, json.dumps({
        "device_key": device_env["soil_key"],
        "measured_at": _ts(), "moisture_pct": "29.0",
    }), credentials=BusCredentials(username="gateway", password=""))
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert hist.json()["meta"]["total"] == 1
    assert hist.json()["items"][0]["source"] == "mqtt"
    # a foreign key inside the payload is rejected just the same
    bus.publish(topic, json.dumps({
        "device_key": device_env["wx_key"],
        "measured_at": _ts(1), "moisture_pct": "29.0",
    }), credentials=BusCredentials())
    hist2 = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert hist2.json()["meta"]["total"] == 1


def test_revoked_device_key_rejected_on_bus(client, bus, device_env):
    dev_id = device_env["soil"]["id"]
    r = client.post(f"/api/v1/devices/{dev_id}/revoke",
                    headers=device_env["headers"])
    assert r.status_code == 200
    topic = build_topic(BASE, device_env["farm_id"], "PROBE-1", "soil")
    bus.publish(topic, json.dumps({"measured_at": _ts(),
                                   "moisture_pct": "33"}),
                credentials=BusCredentials(password=device_env["soil_key"]))
    hist = client.get(
        f"/api/v1/soil/history?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert hist.json()["meta"]["total"] == 0
