#!/usr/bin/env python
"""ASIIS Phase 2 — ESP32-style field sensor simulator (spec-sanctioned:
"Use realistic sensor simulators during software development where physical
hardware is unavailable").

Emulates two field units — a soil probe and a weather station — publishing
through the REAL device channel:

  * transport=mqtt       : paho-mqtt to a broker (username = device code,
                           password = device API key), topic schema
                           {base}/{farm_id}/{code}/telemetry/{kind};
  * transport=http       : POST /api/v1/telemetry/{soil|weather} with the
                           X-Device-Key header (same ingestion pipeline);
  * transport=inprocess  : the app's in-process fallback bus with the
                           identical topic schema (embedded use: run from
                           backend/ in the same Python process as a
                           registered subscriber — used by tests/dev shell);
  * transport=auto       : MQTT if a broker is reachable, else HTTP.

Scenarios (--scenario):
  normal   plausible values with sensor noise + ~3% random message dropouts
  drift    moisture creeps upward every report until it leaves the probe's
           operating range -> OUT_OF_RANGE fault engine fires
  stale    publishes normally, then goes SILENT after --stale-after seconds
           -> the staleness scan flags the device
  failure  stuck-sensor signature: identical consecutive values (FLATLINE)
           mixed with junk readings that pass hard schema limits but violate
           hardware spec bounds (OUT_OF_RANGE)

Provenance: pass --simulate to stamp every reading `simulated: true`; rows
are then persisted with is_simulated=true exactly like the MQTT/HTTP
pipeline defines. Without it the readings store as unflagged (default for
parity with real hardware payloads).

Everything is deterministic under --seed: same seed + same start timestamp
=> identical reading sequences (tests rely on this).

Examples (from backend/):

  # register two sim devices on farm 1 as a logged-in farm manager
  py -m scripts.sensor_simulator --base-url http://127.0.0.1:8000/api/v1 \
     --farm-id 1 --email farmer@agrosmart.farmmail.org --password 'pw' \
     --register

  # 10-minute normal run, one report / 15 s, simulated provenance, fixed seed
  py -m scripts.sensor_simulator --soil-key dkey_... --wx-key dkey_... \
     --farm-id 1 --scenario normal --interval 15 --duration 600 \
     --seed 42 --simulate

  # creeping-failure demo against the dev API
  py -m scripts.sensor_simulator --soil-key dkey_... --farm-id 1 \
     --scenario drift --interval 2 --duration 60 --simulate
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

HARD_LIMITS_SOIL_MOISTURE = (-50.0, 150.0)   # mirrors SoilTelemetryIn
HARD_LIMITS_SOIL_TEMP = (-100.0, 150.0)


# ---------------------------------------------------------------------------
# Deterministic reading generation (pure functions — unit-tested)
# ---------------------------------------------------------------------------

def _diurnal_temp_c(hour_float: float, rng: random.Random) -> float:
    """Generic day/night cycle (physical sine, peak ~15:00) + noise.
    Purely kinematic — no climatological claim is made about any site."""
    base = 23.0 + 7.0 * math.sin((hour_float - 9.0) / 24.0 * 2 * math.pi)
    return round(base + rng.uniform(-0.6, 0.6), 2)


def soil_reading(cfg: "SimulatorConfig", rng: random.Random,
                 step: int, ts: datetime) -> dict:
    """One soil-probe report. Scenario behaviour is documented per case;
    values always stay inside the API's HARD schema limits so the pipeline
    stores them (fault detection, not rejection, is what scenarios demo)."""
    if cfg.scenario == "drift":
        # creeping contamination/sensor drift: +1.5 %VWC per report from a
        # plausible 58 % — crosses the 65 % operating bound after a few
        # steps, which is exactly when the fault engine must fire.
        moisture = min(149.0, 58.0 + 1.5 * step + rng.uniform(-0.2, 0.2))
        temp = round(21.0 + rng.uniform(-0.4, 0.4), 2)
    elif cfg.scenario == "failure":
        # stuck ADC line: bit-identical moisture forever; temperature
        # oscillates between two junk constants (out of probe spec,
        # inside hard schema limits so they are stored + flagged)
        moisture = 42.0
        temp = 95.0 if step % 2 else -30.0
    else:  # normal / stale behave alike while they speak
        # gentle drying trend around a re-watering sawtooth + probe noise
        trend = 28.0 - (step % 20) * 0.35
        moisture = round(trend + rng.uniform(-0.8, 0.8), 2)
        moisture = max(HARD_LIMITS_SOIL_MOISTURE[0] + 0.1,
                       min(HARD_LIMITS_SOIL_MOISTURE[1] - 0.1, moisture))
        temp = round(19.0 + 5.0 * math.sin((ts.hour + ts.minute / 60 - 9) / 24 * 2 * math.pi)
                     + rng.uniform(-0.5, 0.5), 2)
        temp = max(HARD_LIMITS_SOIL_TEMP[0] + 0.1,
                   min(HARD_LIMITS_SOIL_TEMP[1] - 0.1, temp))
    reading = {
        "measured_at": ts.isoformat(),
        "moisture_pct": f"{moisture:.2f}",
        "temperature_c": f"{temp:.2f}",
        "ec_mS_cm": f"{max(0.05, 1.1 + rng.uniform(-0.05, 0.05)):.3f}",
        "probe_depth_cm": str(cfg.probe_depth_cm),
    }
    if cfg.simulate:
        reading["simulated"] = True
    return reading


def weather_reading(cfg: "SimulatorConfig", rng: random.Random,
                    step: int, ts: datetime) -> dict:
    """One farm-level weather-station report (anemometer/pyranometer-style
    behaviour: noise, floor at zero, diurnal solar arc, tipping-bucket
    rain only sometimes). No agricultural claims — instrument emulation."""
    hour = ts.hour + ts.minute / 60.0
    temp = _diurnal_temp_c(hour, rng)
    humidity = max(15.0, min(98.0, round(78.0 - (temp - 21.0) * 3.2
                                         + rng.uniform(-3.0, 3.0), 1)))
    solar = max(0.0, round(820.0 * math.sin(max(0.0, (hour - 6.0)) / 12.0 * math.pi), 1)) \
        if 6.0 <= hour <= 18.0 else 0.0
    wind = round(max(0.0, 2.6 + rng.uniform(-1.4, 2.8)), 2)
    rain = round(rng.uniform(0.2, 6.0), 1) if rng.random() < 0.07 else 0.0
    reading = {
        "measured_at": ts.isoformat(),
        "temperature_c": f"{temp:.2f}",
        "humidity_pct": f"{humidity:.1f}",
        "wind_speed_m_s": f"{wind:.2f}",
        "wind_direction_deg": f"{rng.randint(0, 359)}",
        "solar_radiation_w_m2": f"{solar:.1f}",
        "rainfall_mm": f"{rain:.1f}",
        "pressure_hpa": f"{1013.0 + rng.uniform(-3.0, 3.0):.1f}",
    }
    if cfg.simulate:
        reading["simulated"] = True
    return reading


def speaks_this_step(cfg: "SimulatorConfig", rng: random.Random,
                     step: int, ts: datetime) -> bool:
    """Stale scenario: silent after the cutoff. Others: ~3% radio dropouts."""
    if cfg.scenario == "stale":
        return (ts - cfg.start_time).total_seconds() < cfg.stale_after_s
    return True  # dropouts consume the rng in run(), not here (determinism)


@dataclass
class SimulatorConfig:
    farm_id: int
    soil_key: str | None = None
    wx_key: str | None = None
    soil_code: str = "PROBE-SIM-1"
    wx_code: str = "WX-SIM-1"
    scenario: str = "normal"
    interval_s: float = 10.0
    duration_s: float = 120.0
    seed: int | None = None
    simulate: bool = False
    stale_after_s: float = 30.0
    probe_depth_cm: float = 20.0
    dropout_probability: float = 0.03
    start_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.scenario not in ("normal", "drift", "stale", "failure"):
            raise ValueError(f"unknown scenario {self.scenario!r}")
        if not (self.soil_key or self.wx_key):
            raise ValueError("at least one of soil_key/wx_key is required")
        # normalise start_time to the naive-UTC the pipeline expects
        if self.start_time.tzinfo is not None:
            self.start_time = self.start_time.astimezone(timezone.utc)\
                .replace(tzinfo=None)


def build_step(cfg: SimulatorConfig, rng: random.Random, step: int):
    """Return (soil_batch|None, wx_batch|None) for one time step, applying
    scenario silence and radio dropouts. Pure under a seeded rng."""
    ts = cfg.start_time + timedelta(seconds=cfg.interval_s * step)
    if not speaks_this_step(cfg, rng, step, ts):
        return None, None
    if rng.random() < cfg.dropout_probability:
        return None, None  # ESP32 wifi/MQTT publish lost
    soil = soil_reading(cfg, rng, step, ts) if cfg.soil_key else None
    wx = weather_reading(cfg, rng, step, ts) if cfg.wx_key else None
    return ([soil] if soil else None), ([wx] if wx else None)


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

class TransportError(RuntimeError):
    pass


class HttpTransport:
    """Device-key POSTs against the running API (ESP32 HTTP fallback path)."""

    name = "http"

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        import httpx
        self._httpx = httpx
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def send(self, kind: str, key: str, code: str, farm_id: int,
             readings: list[dict]) -> dict:
        # code/farm_id are unused on HTTP (bound to the key) — kept for a
        # uniform transport signature.
        resp = self._httpx.post(
            f"{self.base_url}/telemetry/{kind}",
            headers={"X-Device-Key": key},
            json={"readings": readings},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


class MqttTransport:
    """Real broker path: one connection per device (code + API key),
    publishing to the channel's topic schema."""

    name = "mqtt"

    def __init__(self, host: str, port: int, base_topic: str,
                 tls: bool = False, ca_certs: str = "",
                 timeout_s: float = 3.0) -> None:
        import paho.mqtt.client as mqtt  # fail fast if absent
        self._mqtt = mqtt
        self.host, self.port = host, port
        self.base_topic = base_topic.strip("/")
        self.timeout_s = timeout_s
        self.tls = tls
        self.ca_certs = ca_certs
        self._clients: dict[str, object] = {}

    def _client(self, code: str, key: str):
        if code in self._clients:
            return self._clients[code]
        c = self._mqtt.Client(callback_api_version=self._mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"sim-{code}-{random.randint(1000, 9999)}",
                              protocol=self._mqtt.MQTTv311)
        c.username_pw_set(code, key)  # broker verifies against its passwd file
        if self.tls:
            if not self.ca_certs:
                raise TransportError("MQTT TLS enabled but no CA file configured")
            c.tls_set(ca_certs=self.ca_certs)
        try:
            c.connect(self.host, self.port, keepalive=30)
        except OSError as exc:
            raise TransportError(f"broker unreachable: {exc}") from exc
        c.loop_start()
        self._clients[code] = c
        return c

    def send(self, kind: str, key: str, code: str, farm_id: int,
             readings: list[dict]) -> dict:
        from app.iot.topics import build_topic  # schema shared with backend
        client = self._client(code, key)
        topic = build_topic(self.base_topic, farm_id, code, kind)
        infos = [client.publish(topic, json.dumps(r)) for r in readings]
        for info in infos:
            info.wait_for_publish(timeout=self.timeout_s)
        return {"transport": "mqtt", "topic": topic,
                "published": sum(1 for i in infos if i.rc == 0)}

    def close(self) -> None:
        for c in self._clients.values():
            c.loop_stop()
            c.disconnect()
        self._clients.clear()


class InProcessTransport:
    """Embedded fallback bus (same process as the backend app): publishes
    with the identical topic schema; the real handler + pipeline run."""

    name = "inprocess"

    def __init__(self) -> None:
        from app.core.config import get_settings
        from app.db.session import SessionLocal
        from app.iot.bus import BusCredentials, get_bus
        from app.iot.handler import make_bus_subscriber
        from app.iot.topics import subscription_wildcard
        self._base = get_settings().MQTT_BASE_TOPIC
        self._bus = get_bus()
        self._creds = BusCredentials
        self._token = self._bus.subscribe(
            subscription_wildcard(self._base),
            make_bus_subscriber(SessionLocal, self._base),
        )

    def send(self, kind: str, key: str, code: str, farm_id: int,
             readings: list[dict]) -> dict:
        from app.iot.topics import build_topic
        topic = build_topic(self._base, farm_id, code, kind)
        n = self._bus.publish(topic, json.dumps({"readings": readings}),
                              credentials=self._creds(username=code,
                                                      password=key))
        return {"transport": "inprocess", "topic": topic, "subscribers": n}

    def close(self) -> None:
        self._bus.unsubscribe(self._token)


def make_transport(cfg_args) -> tuple[object, str]:
    """Resolve --transport (auto = MQTT if reachable else HTTP)."""
    if cfg_args.transport == "inprocess":
        return InProcessTransport(), "inprocess"
    if cfg_args.transport in ("mqtt", "auto"):
        t = MqttTransport(cfg_args.mqtt_host, cfg_args.mqtt_port,
                          cfg_args.base_topic, tls=cfg_args.mqtt_tls,
                          ca_certs=cfg_args.mqtt_ca)
        try:
            t._client("PROBE-CONNTEST", "dkey_connectivity_probe")
            t.close()
            return t, "mqtt"
        except TransportError as exc:
            if cfg_args.transport == "mqtt":
                raise SystemExit(f"--transport mqtt requested but {exc}")
            print(f"[sim] MQTT unavailable ({exc}); falling back to HTTP",
                  file=sys.stderr)
    return HttpTransport(cfg_args.base_url), "http"


# ---------------------------------------------------------------------------
# Device registration convenience (human-driven, uses normal auth)
# ---------------------------------------------------------------------------

def register_sim_devices(base_url: str, email: str, password: str,
                         farm_id: int, soil_code: str, wx_code: str) -> dict:
    """Register (or re-register -> key rotation) the two sim devices via
    the real /devices API and return their one-time plaintext keys."""
    import httpx
    login = httpx.post(f"{base_url}/auth/login",
                       json={"email": email, "password": password}, timeout=10)
    login.raise_for_status()
    headers = {"Authorization":
               f"Bearer {login.json()['tokens']['access_token']}"}
    out = {}
    for label, code, dtype in (("soil", soil_code, "soil_probe"),
                               ("wx", wx_code, "weather_station")):
        if not code:
            continue
        r = httpx.post(f"{base_url}/devices", headers=headers, json={
            "farm_id": farm_id, "code": code, "name": f"Simulator {code}",
            "device_type": dtype, "model": "ASIIS-SIM-ESP32",
            "firmware_version": "sim-1.0",
        }, timeout=10)
        r.raise_for_status()
        out[label] = r.json()["api_key"]
        out[label + "_id"] = r.json()["device"]["id"]
    return out


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------

def run(cfg: SimulatorConfig, transport, *, steps: int | None = None,
        sleep_fn=time.sleep, verbose: bool = True) -> dict:
    """Publish `duration` of readings; returns a summary. steps=single-step
    loop override (tests)."""
    rng = random.Random(cfg.seed)
    n_steps = steps if steps is not None \
        else max(1, int(cfg.duration_s // max(cfg.interval_s, 0.001)))
    sent = {"soil": 0, "weather": 0}
    skipped = 0
    results = []
    for step in range(n_steps):
        ts = cfg.start_time + timedelta(seconds=cfg.interval_s * step)
        soil_batch, wx_batch = build_step(cfg, rng, step)
        if soil_batch is None and wx_batch is None:
            skipped += 1
        if soil_batch:
            res = _send(transport, cfg, "soil", cfg.soil_code, cfg.soil_key,
                        soil_batch)
            sent["soil"] += len(soil_batch)
            results.append(res)
        if wx_batch:
            res = _send(transport, cfg, "weather", cfg.wx_code, cfg.wx_key,
                        wx_batch)
            sent["weather"] += len(wx_batch)
            results.append(res)
        if verbose:
            print(f"[sim] step {step + 1}/{n_steps} t={ts.isoformat()} "
                  f"soil={'y' if soil_batch else '-'} wx={'y' if wx_batch else '-'}")
        if step < n_steps - 1 and cfg.interval_s > 0:
            sleep_fn(cfg.interval_s)
    summary = {"transport": getattr(transport, "name", "?"),
               "scenario": cfg.scenario, "steps": n_steps,
               "skipped_steps": skipped, "sent": sent}
    if verbose:
        print(f"[sim] done: {json.dumps(summary)}")
    return summary


def _send(transport, cfg, kind, code, key, batch) -> dict:
    return transport.send(kind, key, code, cfg.farm_id, batch)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="sensor_simulator", description=__doc__.split("Examples")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--farm-id", type=int, required=True)
    ap.add_argument("--base-url",
                    default="http://127.0.0.1:8000/api/v1")
    ap.add_argument("--transport", choices=["auto", "mqtt", "http", "inprocess"],
                    default="auto",
                    help="auto = MQTT if broker reachable, else HTTP; "
                         "inprocess = embedded fallback bus (same process)")
    ap.add_argument("--mqtt-host", default="127.0.0.1")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--base-topic", default="asiis/v1")
    ap.add_argument("--mqtt-tls", action="store_true",
                    help="TLS to the broker; requires --mqtt-ca")
    ap.add_argument("--mqtt-ca", default="", help="broker CA file (PEM)")
    ap.add_argument("--soil-key", default=None, help="device API key dkey_…")
    ap.add_argument("--wx-key", default=None)
    ap.add_argument("--soil-code", default="PROBE-SIM-1")
    ap.add_argument("--wx-code", default="WX-SIM-1")
    ap.add_argument("--scenario", choices=["normal", "drift", "stale", "failure"],
                    default="normal")
    ap.add_argument("--interval", type=float, default=10.0,
                    help="seconds between reports")
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--stale-after", type=float, default=30.0,
                    help="stale scenario: seconds of speech before silence")
    ap.add_argument("--seed", type=int, default=None,
                    help="deterministic run (same seed + start => same data)")
    ap.add_argument("--simulate", action="store_true",
                    help="stamp readings simulated=true (is_simulated provenance)")
    ap.add_argument("--register", action="store_true",
                    help="register/rotate the sim devices first using "
                         "--email/--password, print the one-time keys, and "
                         "run with them")
    ap.add_argument("--email", default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.register:
        if not (args.email and args.password):
            ap.error("--register needs --email and --password")
        keys = register_sim_devices(args.base_url, args.email, args.password,
                                    args.farm_id, args.soil_code, args.wx_code)
        args.soil_key = keys.get("soil", args.soil_key)
        args.wx_key = keys.get("wx", args.wx_key)
        print("Registered sim devices — ONE-TIME keys (store them now):")
        if "soil" in keys:
            print(f"  soil {args.soil_code}: {keys['soil']}")
        if "wx" in keys:
            print(f"  wx   {args.wx_code}: {keys['wx']}")

    cfg = SimulatorConfig(
        farm_id=args.farm_id, soil_key=args.soil_key, wx_key=args.wx_key,
        soil_code=args.soil_code, wx_code=args.wx_code,
        scenario=args.scenario, interval_s=args.interval,
        duration_s=args.duration, seed=args.seed, simulate=args.simulate,
        stale_after_s=args.stale_after,
    )
    transport, tname = make_transport(args)
    if not args.quiet:
        print(f"[sim] transport={tname} scenario={cfg.scenario} "
              f"farm={cfg.farm_id} interval={cfg.interval_s}s "
              f"duration={cfg.duration_s}s seed={cfg.seed} "
              f"simulate_flag={cfg.simulate}")
    try:
        run(cfg, transport, verbose=not args.quiet)
    finally:
        if hasattr(transport, "close"):
            transport.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
