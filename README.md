# ASIIS — AgroSmart Irrigation Intelligence System

AI-powered smart irrigation management platform (18 modules, 6 delivery
phases). **Phases 1–2 are implemented end-to-end**: user authentication &
role management, farm & irrigation-zone management, RBAC, audit trail, web
UI, migrations, and automated tests — plus soil/weather telemetry ingestion
(HTTP + MQTT), device registry with per-device API keys, sensor fault
detection, forecast providers, sensor simulators, and their UI pages. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the phase plan and design decisions.

## Stack

- Backend: Python FastAPI + SQLAlchemy 2 + Alembic, JWT auth, bcrypt
- Database: SQLite by default (zero-dependency local dev); PostgreSQL/PostGIS
  target for production (set `DATABASE_URL`, see `docker-compose.yml`)
- Frontend: Next.js 15 (App Router), live API calls only — no mock screens

## Prerequisites

- Python 3.11+ (`py` launcher on Windows) and Node.js 18+

## Run the backend

From `backend/`:

```bash
# 1. create the virtualenv (first time only)
py -m venv .venv            # Windows        (Linux/macOS: python3 -m venv .venv)
.venv/Scripts/activate      # Windows        (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

# 2. configure (optional — defaults work for local dev)
copy .env.example .env      # then set SECRET_KEY for anything non-local

# 3. run (creates dev tables + seeds the RBAC catalog on first start)
pip install -r requirements-dev.txt   # only if you want to run tests
uvicorn app.main:app --reload --port 8000
```

- API: http://127.0.0.1:8000/api/v1 — interactive docs at http://127.0.0.1:8000/docs
- Production-style schema management: `alembic upgrade head`
  (initial migration included; set `AUTO_CREATE_TABLES=false`)

### Create the first administrator

Self-registration always yields a **farm_manager** (never an admin). To
bootstrap the first admin deliberately:

```bash
py -m scripts.bootstrap_admin --email you@example.com --name "Your Name"
```

### Run backend tests

```bash
pip install -r requirements-dev.txt
pytest              # 142 tests: auth, RBAC, farms, zones, audit, devices,
                    # telemetry ingestion, faults, soil/weather reads,
                    # forecast providers, MQTT channel, simulator
pytest --cov=app    # with coverage
```

## Run the frontend

From `frontend/`:

```bash
npm install
npm run dev         # http://localhost:3000  (dev, calls API at 127.0.0.1:8000)
```

```bash
npm test            # node:test unit tests (permission rule)
npm run build       # production build check
npm run start       # serve the production build
```

Point the UI at a non-local API with `NEXT_PUBLIC_API_BASE_URL` at build time.

## Sensing & devices (Phase 2)

Phase 2 needs physical hardware for nothing: the spec-sanctioned simulator
publishes through the same ingestion pipeline real devices use.

1. **Register devices** in the UI (`/devices`) or with the simulator's
   `--register` mode. Each registration returns a plaintext `dkey_...`
   API key **once** — it is stored hashed and can only be replaced by
   rotation.
2. **Send telemetry** over HTTP (`POST /api/v1/telemetry/soil|weather`
   with `X-Device-Key`) or over MQTT — see
   [IoT transport (MQTT)](#iot-transport-mqtt) for both paths and the
   topic grammar. Ingestion, validation and fault handling are shared,
   so the source only shows up as a `source` provenance badge.
3. **Run the simulator** (from `backend/`). `--register` logs in as the
   given user, creates a soil probe (`PROBE-SIM-1`) and a weather station
   (`WX-SIM-1`) on the farm and prints both device keys once — then keeps
   publishing with them for `--duration` seconds. Re-run without
   `--register` and pass `--soil-key`/`--wx-key` to reuse the devices.

   ```bash
   # register the two sim devices on farm 1 and publish 60 s of readings
   .venv/Scripts/activate
   python -m scripts.sensor_simulator --register --farm-id 1 \
     --email farmer@agrosmart.local --password 'pw' \
     --interval 5 --duration 60 --simulate

   # 10 minutes of soil + weather readings, one report / 15 s, badged simulated
   python -m scripts.sensor_simulator --soil-key dkey_... --wx-key dkey_... \
     --farm-id 1 --scenario normal --interval 15 --duration 600 --seed 42 --simulate

   # fault-engine demos: drift (out-of-range), failure (flatline), stale (silence)
   python -m scripts.sensor_simulator --soil-key dkey_... --farm-id 1 \
     --scenario drift --interval 2 --duration 60 --simulate
   ```

4. **Look at the data** in the UI: `/sensor-data` (latest soil + weather,
   forecast refresh) and `/faults` (stale / out-of-range / flatline /
   auth-failure events). Rows produced by the simulator are badged
   `simulated` and flagged readings keep their `quality_flags`, so
   synthetic data is never presented as measured.

### Forecast providers
`WEATHER_PROVIDER` picks the default adapter; the UI's forecast panel
lists every provider with honest metadata (`simulated` / `no API key`).
`simulated` is deterministic and always stamps its rows
`provider='simulated', is_simulated=true`. `open_meteo` is the real public
API and needs no key — verified live on 2026-11-06 against latitude 9.9 /
longitude −1.2 (3-day issue: 25.5–36.8 °C, 0.0–0.0 mm precip, 0–4 % rain
probability, wind converted from km/h to m/s, `confidence` left `NULL`
because Open-Meteo publishes none). `open_weather_map` requires
`OPEN_WEATHER_MAP_API_KEY`; with no key it reports itself unconfigured and
a refresh returns `502 weather_provider_error` — real providers never fall
back to synthetic data silently.

To try the real provider: set `WEATHER_PROVIDER=open_meteo` (or choose it
in the UI), make sure the farm has latitude/longitude, and press
**Refresh forecast** on `/sensor-data`.

## IoT transport (MQTT)

Topic grammar (identical on both transports):
`{MQTT_BASE_TOPIC}/{farm_id}/{device_code}/telemetry/{soil|weather}`,
e.g. `asiis/v1/7/PROBE-1/telemetry/soil`. Malformed, wildcard, or
cross-device topics are rejected before the pipeline sees a byte.

- **Real broker** (`MQTT_ENABLED=true`): devices connect over
  TCP/TLS (`MQTT_USE_TLS`, `MQTT_CA_CERTS`) authenticating with
  `username = device code`, `password = device API key`.
  `backend/iot/mosquitto/` holds a ready config plus a per-topic ACL
  example confining every device to `{base}/{farm_id}/{own_code}/#`, so
  authorization is enforced broker-side. A batch payload may be one
  reading object, a list of them, or `{"readings": [...]}`.
- **In-process fallback** (default): the same topic grammar, the same
  handler, the same device-key authentication and the same ingestion and
  fault engine, without a broker or Docker. It is *not* a mock — it is the
  real pipeline with an in-memory transport.
- Tradeoff: the fallback has no TLS (nothing leaves the process) and its
  authentication is consumer-enforced rather than broker-enforced, so it
  is for development, tests, and single-process embedded runs.
  Production uses a TLS broker. A device may additionally carry
  `"device_key"` in the payload, which the handler verifies against the
  topic's device even if the broker were misconfigured.
- If a broker is configured but unreachable at startup, the backend logs a
  warning and keeps the fallback bus — it never pretends to be connected.
  The live-broker path has unit-tested client config but has not been run
  against a real mosquitto instance from this machine (no Docker here).

## Typical first session

1. Start backend and frontend as above.
2. Register at `/register` (becomes a farm_manager).
3. Create a farm, open it, add irrigation zones (area limits and code
   uniqueness are enforced server-side).
4. Bootstrap an admin, log in as admin, and manage users/roles via the API
   (`/docs`) — role edits take effect immediately for new tokens.
5. Check `/api/v1/audit-logs` — every action above is recorded with actor,
   resource, and IP.
6. Phase 2: register a soil probe and a weather station under `/devices`,
   run the simulator against their keys, then watch readings arrive under
   `/sensor-data` and fault events under `/faults`.

## Configuration reference (backend env / .env)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./agrosmart.db` | DB engine; Postgres/PostGIS in prod |
| `SECRET_KEY` | dev placeholder | **override in any deployment** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | JWT lifetime |
| `BCRYPT_ROUNDS` | `12` | password work factor |
| `CORS_ORIGINS` | localhost:3000 | allowed web origins (JSON list) |
| `DEFAULT_SELF_REGISTRATION_ROLE` | `farm_manager` | role granted on signup |
| `AUTO_CREATE_TABLES` | `true` (dev) | use Alembic instead in prod |
| `TELEMETRY_STALE_MINUTES` | `120` | no reading this long ⇒ device stale |
| `FLATLINE_CONSECUTIVE_READINGS` | `3` | identical readings ⇒ flatline fault |
| `TELEMETRY_OPERATING_RANGES` | `{}` (spec defaults) | hardware-limit overrides for out-of-range faults (JSON) |
| `WEATHER_PROVIDER` | `simulated` | `simulated` / `open_meteo` / `open_weather_map` |
| `OPEN_WEATHER_MAP_API_KEY` | empty | key extension point; empty ⇒ provider unconfigured |
| `MQTT_ENABLED` | `false` | real broker; otherwise the in-process fallback bus |
| `MQTT_BASE_TOPIC` | `asiis/v1` | topic grammar `{base}/{farm}/{code}/telemetry/{kind}` |

## Production infrastructure (Phase 6)

`docker-compose.yml` provides PostGIS + Redis for parity with the target
stack; the API/frontend containers arrive with the deployment phase. The app
runs fully without them via the SQLite default. `mosquitto` is included for
the Phase 2 device channel: `docker compose up mosquitto` then
`MQTT_ENABLED=true` (the broker config is not yet verified on a machine with
Docker — until it is, the in-process bus serves the same topic schema).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Modules 1–2 foundation: auth, RBAC, farms, zones, audit, web UI, tests, docs | **Complete** |
| 2 | Soil + weather data, MQTT telemetry, device auth, sensor simulators | **Complete** |
| 3 | Crop ID, crop knowledge DB, FAO Penman-Monteith ET engine, scheduling | Next |
| 4 | Sprinkler/valve control, safety interlocks, automation rules, water accounting | Planned |
| 5 | Advisory, notifications, reports, mobile | Planned |
| 6 | Admin/config, AI learning loop, production infra, backup/recovery | Planned |
