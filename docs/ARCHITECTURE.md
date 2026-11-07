# ASIIS Architecture — AgroSmart Irrigation Intelligence System

Version 0.1 (Phase 1 implemented). This document is the reference the project
specification calls for: it defines the **six implementation phases** and maps
all **18 modules** onto them, and it records the design decisions that Phase 1
code already enforces.

---

## 1. System overview

ASIIS is a modular, API-driven platform that identifies crops, monitors
agricultural conditions, calculates crop water requirements using FAO
evapotranspiration science, and safely controls sprinkler irrigation.

```
                        ┌─────────────────────────────┐
  Browser / Mobile ───▶ │  Frontend (Next.js / Flutter)│
                        └──────────────┬──────────────┘
                                       │ HTTPS + JWT
                        ┌──────────────▼──────────────┐
                        │  FastAPI (REST /api/v1)      │
                        │  routers → services → models │
                        └──┬─────────┬─────────┬───────┘
                           │         │         │
              ┌────────────▼──┐  ┌───▼─────┐  ┌▼──────────────┐
              │ PostgreSQL /  │  │ Redis + │  │ MQTT broker   │
              │ PostGIS       │  │ Celery  │  │ (ESP32/RPi)   │
              └───────────────┘  └─────────┘  └───────────────┘
```

**Stack:** Python FastAPI · SQLAlchemy 2 + Alembic · PostgreSQL/PostGIS
(SQLite fallback for dev) · Next.js (web) · Flutter (mobile, Phase 5) ·
Celery/Redis (background jobs) · MQTT (device transport) · PyTorch/OpenCV
(vision + ML, Phase 2–3).

**Layering rule (enforced by structure):**
`app/api/v1/routes` (HTTP, auth, permissions) → `app/services` (business
rules, no HTTP concepts) → `app/models` (persistence) with `app/schemas`
(wire-format validation). No route touches the ORM directly; no service
imports FastAPI.

---

## 2. The six implementation phases

Phases are dependency-ordered: each uses only capabilities built before it.

### Phase 1 — Foundation: identity, land, and access *(implemented)*
Modules: **1** (User Authentication & Role Management), **2** (Farm &
Agricultural Land Management), plus the cross-cutting audit trail.
Delivers: project scaffold, config, DB layer + migrations, RBAC, JWT auth,
farm/zone CRUD with ownership scoping, web login/register/farm screens,
automated test suite.
Exit criteria: acceptance reqs 1 & 2 demonstrable through the real API/UI;
every state change auditable.

### Phase 2 — Sensing & data acquisition *(implemented)*
Modules: **5** (Soil Intelligence & Moisture Monitoring), **6** (Weather
Intelligence & Forecast Integration), plus the core of **9** (IoT hardware
communication: MQTT ingestion, device auth, sensor failure detection) and a
realistic **sensor simulator** for development without hardware.
Data: soil probe readings, weather observations + forecast provider
integration (open data: Open-Meteo/NOAA-class APIs), device registry,
telemetry time series.
Exit criteria: acceptance reqs 5 & 6 — readings received, recorded, and
weather influencing recommendations; missing/stale sensors raise alerts.

Status: the sensing half is delivered end-to-end — device registry with
per-device API keys, HTTP + MQTT ingestion, the soil/weather time series,
the fault engine (stale / out-of-range / flatline / auth-failure),
forecast provider integration, simulators, and UI pages (`/devices`,
`/sensor-data`, `/faults`). Two clauses land later, by plan: weather
*influencing recommendations* needs Phase 3's ET engine, and fault
*notifications* (push/email) are Module 14 in Phase 5 — Phase 2 surfaces
faults as queryable events plus UI badges. The real-broker path is wired
and unit-tested through the identical in-process bus; it has not been
exercised against a live mosquitto instance (no Docker on the dev
machine), so that verification is still open.

### Phase 3 — Agricultural intelligence
Modules: **3** (AI Crop & Plant Identification), **4** (Crop Knowledge
Database), **7** (Irrigation Scheduling Engine), **12** (Crop Health &
Growth Monitoring, initial).
Science: FAO Penman-Monteith ET₀, crop coefficients Kc per growth stage
(from published FAO-56 tables — *ingested as validated research data, never
invented*), soil-water balance, effective rainfall, root-zone depletion,
irrigation efficiency, application rates.
Exit criteria: acceptance reqs 3, 4, 7 — a schedule for a real field computed
from measured weather + soil + validated crop parameters.

### Phase 4 — Automation & control
Modules: **8** (Smart Sprinkler Distribution), **13** (Automation Rules &
Control Centre), **11** (Water Resource & Consumption Management), the
**safety envelope** of **9** (device command channel, hardware interlocks,
emergency stop, offline local control on ESP32/RPi gateway), pump protection
and leak detection.
Modes: fully automatic / semi-automatic / manual / scheduled / sensor-
triggered / weather-adjusted, with per-zone independence.
Rule: no AI prediction may actuate hardware directly; only rules inside the
validated safety envelope control valves (spec: "Do not allow unvalidated AI
predictions to independently control physical irrigation equipment").
Exit criteria: acceptance reqs 8, 10, 11 — sprinklers controlled safely,
consumption metered, safe local operation without internet.

### Phase 5 — Delivery & field operations
Modules: **10** (AI Agricultural Advisory), **14** (Notifications & Alerts),
**15** (Reports & Analytics), **16** (Mobile Application & Field Operations,
Flutter + responsive web hardening).
Exit criteria: acceptance reqs 9, 12 — farmers receive advice, alerts and
reports on any device.

### Phase 6 — Learning, administration & operations
Modules: **17** (Administration & System Configuration), **18** (AI Learning,
Prediction & Continuous Improvement), production infra: PostGIS migration
path, backup/recovery, telemetry retention, model evaluation/retraining
pipelines, multi-farm dashboards.
Exit criteria: acceptance reqs 13, 14 and full production readiness.

---

## 3. 18-module ↔ phase ↔ status map

| # | Module | Phase | Status |
|---|--------|-------|--------|
| 1 | User Authentication & Role Management | 1 | **Done** |
| 2 | Farm & Agricultural Land Management | 1 | **Done** |
| 3 | AI Crop & Plant Identification | 3 | Planned (extension points in Models 4/7 schemas) |
| 4 | Agricultural Research & Crop Knowledge DB | 3 | Planned |
| 5 | Soil Intelligence & Moisture Monitoring | 2 | **Done** (ingestion, storage, reads, fault flags; ET-based depletion joins Phase 3) |
| 6 | Weather Intelligence & Forecast Integration | 2 | **Done** (observations + provider forecasts, provenance-flagged) |
| 7 | Intelligent Irrigation Scheduling Engine | 3 | Planned |
| 8 | Smart Sprinkler Distribution Management | 4 | Planned |
| 9 | IoT Hardware & Communication Integration | 2 (telemetry) + 4 (control) | **Done for telemetry** (device auth, HTTP + MQTT ingestion, fault detection, simulators); device *control* remains Phase 4 |
| 10 | AI Agricultural Advisory System | 5 | Planned |
| 11 | Water Resource & Consumption Management | 4 | Planned |
| 12 | Crop Health & Growth Monitoring | 3 | Planned |
| 13 | Automation Rules & Control Centre | 4 | Planned |
| 14 | Notifications & Alert Management | 5 | Planned |
| 15 | Agricultural Reports & Analytics | 5 | Planned |
| 16 | Mobile Application & Field Operations | 5 | Planned |
| 17 | Administration & System Configuration | 6 | Planned (auth/roles from Module 1 already admin-capable) |
| 18 | AI Learning, Prediction & Continuous Improvement | 6 | Planned |

---

## 4. Decisions already enforced in code (Phases 1–2)

### 4.1 Database: PostgreSQL/PostGIS target, SQLite dev default
- The spec's production target is PostgreSQL + PostGIS. To keep the
  platform runnable on a plain machine (no PostgreSQL install), **default
  config uses SQLite**; `DATABASE_URL` switches engines with no code change.
- `geometry` fields are GeoJSON **text** on SQLite and become PostGIS
  `GEOGRAPHY` columns in a Phase 6 migration (`backend/alembic`).
  Alembic `env.py` renders batch mode on SQLite and would import
  `geoalchemy2` only when the dialect is PostgreSQL.
- Schema changes in production go through Alembic
  (`alembic upgrade head`); `AUTO_CREATE_TABLES` is a dev-only bootstrap.

### 4.2 RBAC model
- Roles (admin, farm_manager, operator, advisor, viewer) and permissions
  (`resource.action[.own|.all]`) are defined in code
  (`app/core/permissions.py`) and materialised into DB tables on first boot;
  afterwards DB is authoritative for *assignments* so administrators can
  tune roles (`role.manage`) without redeploying code.
- Scope rule: holding `x.all` implies `x.own`. Enforced in one function —
  `satisfies()` — mirrored on the client only as a UI hint.
- Ownership: farms have exactly one owner (`users.id`) in Phase 1.
  Multi-user farm membership (organizations/teams) is a documented Phase 6
  extension; until then admins create resources on behalf of users
  (`owner_id` on `POST /farms`).
- Cross-owner resources return **404, not 403** (no resource enumeration).
- Self-registration yields `farm_manager` (configurable via
  `DEFAULT_SELF_REGISTRATION_ROLE`). **No password is ever hardcoded**:
  the first admin comes from `scripts/bootstrap_admin.py`, everything else
  via the public register flow.

### 4.3 AuthN/AuthZ
- bcrypt password hashing (configurable work factor, default 12).
- HS256 JWT access + refresh tokens with `jti`/`exp`; stateless deny-listing
  (logout revocation) is a documented extension for the Redis phase.
- All permission checks are FastAPI dependencies (`require_permissions`)
  **plus** service-level ownership checks — defence in depth.
- Consistent error envelope `{"error":{"code","message"}}` from typed
  domain exceptions; DB uniqueness races map to 409.

### 4.4 Audit trail
- Append-only `audit_logs`: register, login, and every farm/zone/role
  mutation with actor, action, resource, JSON details, and client IP.
  Access scoped: `audit.read` own activity; `audit.read.all` admin.

### 4.5 Business rules without invented science
- Zone areas cannot exceed declared farm area; farm/zone codes unique per
  owner/farm; deleting a farm requires removing zones first; soft-deleted
  records tombstone their unique codes so they can be reused.
- `max_application_mm_per_hour` on zones is an **operator-entered limit**
  (safety cap input), never a fabricated default. True agronomic rates come
  from the Phase-3 ET engine.
- Forward references (crop, sensors, valves) are documented extension
  points in models/schemas — no fake tables or mock endpoints exist.

### 4.6 No mock interfaces (spec rule)
Every screen performs live API calls; every API reads/writes the real
database. The only simulators permitted by the spec are *hardware* sensor
simulators — delivered in Phase 2 as `scripts/sensor_simulator.py`, which
publish through the real device channel (HTTP or MQTT), not around it.

### 4.7 Decisions added in Phase 2 code

- **Device credentials are separate from user JWTs.** Device keys are
  random (`dkey_…`), stored only as bcrypt hashes with a 13-character
  `key_prefix` for identification; the plaintext is returned exactly once
  by register/rotate. Rotation and revocation take effect immediately.
- **Two hard boundaries on ingestion**, in order: Pydantic hard limits
  (values meaningless for *any* sensor ⇒ HTTP 422, nothing stored) and
  hardware *operating ranges* in `telemetry_service` (implausible but
  formattable ⇒ stored as evidence **and** flagged `out_of_range`).
  Operating ranges are device spec limits, never invented agronomic
  thresholds, and are overridable via `TELEMETRY_OPERATING_RANGES`.
- **Faults are events, not booleans.** `stale_data`, `out_of_range`,
  `flatline` and `auth_failure` open and resolve as rows in
  `sensor_fault_events`; staleness is *derived* from `last_seen_at` at
  read time (no scheduler needed — `GET /faults` sweeps first).
- **Provenance travels with every reading**: `is_simulated`, `source`
  (device HTTP / MQTT) and per-row `quality_flags`. The UI badges these
  rather than presenting simulator output as measured data.
- **Transport is swappable, the pipeline is not.** MQTT (paho + broker
  ACLs + optional TLS) and the dependency-free in-process bus share one
  topic grammar and one handler, so both paths run the same validation,
  dedup, and fault logic. If a real broker is unavailable the app logs
  loudly and keeps the fallback bus — it never pretends to be connected.
- **Weather providers are capability-described, never silently faked.**
  The registry reports `is_simulated` / `requires_api_key` / `configured`;
  a real provider that is unreachable or unconfigured returns
  `502 weather_provider_error` instead of falling back to synthetic rows,
  and forecast rows only ever exist because a provider wrote them.

---

## 5. API surface (all under `/api/v1`)

### Phase 1

| Method+path | Permission(s) | Notes |
|---|---|---|
| POST `/auth/register` | public | creates farm_manager |
| POST `/auth/login` | public | returns token pair + user + permissions |
| POST `/auth/refresh` | refresh token | rotates access token |
| GET `/auth/me` | bearer | current user + effective permissions |
| GET `/users`, POST `/users`, GET `/users/{id}`, PATCH `/users/{id}` | user.read/create/update | admin tooling |
| PUT `/users/{id}/roles` | role.manage | guards self-escalation |
| GET `/roles`, GET `/permissions` | role.read | catalog from DB |
| PATCH `/roles/{code}/permissions` | role.manage | admin keeps role.manage invariant |
| GET/POST `/farms`, GET/PATCH/DELETE `/farms/{id}` | farm.* | ownership-scoped |
| GET/POST `/farms/{id}/zones`, GET/PATCH/DELETE `/zones/{id}` | zone.* + farm access | area + uniqueness rules |
| GET `/audit-logs` | audit.read(.all) | own vs global |
| GET `/health` | public | liveness |

Interactive docs at `/docs` (OpenAPI).

### Phase 2 additions

| Method+path | Auth / permission | Notes |
|---|---|---|
| POST `/devices` | `device.manage` | returns the plaintext device key **once** |
| GET `/devices`, GET `/devices/{id}` | `device.manage` | farm-scoped listing |
| GET `/devices/{id}/status` | `device.manage` | derived staleness + open faults |
| PATCH `/devices/{id}` | `device.manage` | rename, re-zone, model/firmware |
| POST `/devices/{id}/rotate-key` | `device.manage` | new key, old one dead immediately |
| POST `/devices/{id}/revoke` | `device.manage` | device can no longer ingest |
| POST `/telemetry/soil`, POST `/telemetry/weather` | `X-Device-Key` **or** Bearer + `telemetry.ingest` | batch ingestion, idempotent per (device, measured_at) |
| GET `/soil/latest`, `/soil/history` | `soil.read` | provenance + quality flags on every row |
| GET `/weather/latest`, `/weather/history` | `weather.read` | measured observations |
| GET `/weather/forecasts` | `weather.read` | persisted provider issues only |
| GET `/weather/forecast-providers` | `weather.read` | capability metadata (simulated/key/configured) |
| POST `/weather/forecast-refresh` | `weather.read` | pulls a real provider issue, audited |
| GET `/faults` | `faults.read` | runs the staleness sweep, then lists |

MQTT is the second ingestion transport (`MQTT_ENABLED=true`): devices
publish to `{base}/{farm_id}/{device_code}/telemetry/{soil|weather}` with
broker credentials `username=device code`, `password=device key`, and the
payload accepts one reading, a list of readings, or `{"readings": [...]}`.

---

## 6. Repository layout

```
agrosmart/
├── prompt.txt                  # original specification
├── README.md                   # run instructions
├── docker-compose.yml          # prod infra parity (PostGIS, Redis) + mosquitto
├── docs/
│   └── ARCHITECTURE.md         # this document
├── backend/
│   ├── requirements.txt / requirements-dev.txt
│   ├── alembic.ini, alembic/   # migrations (Phase 1 schema + Phase 2
│   │                           # fa5519143126 iot/soil/weather/faults)
│   ├── app/
│   │   ├── main.py             # FastAPI app, lifespan, error envelope
│   │   ├── core/               # config, security, permissions, exceptions
│   │   ├── db/                 # engine/session, declarative base
│   │   ├── models/             # user/rbac, farm/zone, audit, iot/soil/weather
│   │   ├── schemas/            # request/response validation
│   │   ├── services/           # rbac, user, farm/zone, audit, device,
│   │   │                       # telemetry (ingest + faults), forecast,
│   │   │                       # weather_providers/ (simulated, open_meteo,
│   │   │                       # open_weather_map adapters)
│   │   ├── iot/                # MQTT topic grammar, message handler,
│   │   │                       # paho client, in-process fallback bus
│   │   └── api/v1/routes/      # auth, users, roles, farms, zones, audit,
│   │                           # devices, telemetry, faults, soil, weather
│   ├── iot/mosquitto/          # broker config + ACL example (Phase 2)
│   ├── scripts/bootstrap_admin.py
│   ├── scripts/sensor_simulator.py   # spec-sanctioned device simulator
│   └── tests/                  # pytest suite (142 tests)
└── frontend/
    ├── app/                    # Next.js App Router pages: login/register,
    │                           # dashboard, farms/[id], devices,
    │                           # sensor-data, faults
    ├── components/             # Shell (nav/session chrome)
    ├── lib/                    # api client, session store, permission rule
    └── tests/                  # node --test unit tests
```

---

## 7. Testing strategy

- Backend: pytest against an isolated temp SQLite DB, full schema rebuild per
  test, real HTTP layer via TestClient (no mocked services). Covers auth
  flows, token typing, RBAC enforcement and role edits, ownership isolation,
  farm/zone CRUD business rules, audit recording and scoping — and, from
  Phase 2, device key issuance/rotation/revocation, batch ingestion
  (idempotency, timestamp rejection, cross-device protection), the fault
  engine (stale/out-of-range/flatline/auth_failure), soil & weather reads
  with farm scoping, and forecast provider refresh + persistence.
  142 tests total.
- Frontend: production build must compile; pure logic (permission rule)
  unit-tested with node:test. Browser E2E lands with Phase 5 mobile/delivery
  hardening (Playwright).
- Device/IoT: the spec-sanctioned sensor simulator is exercised directly in
  `tests/test_sensor_simulator.py` (deterministic under `--seed`), and the
  MQTT topic grammar/bus/handler are covered in `tests/test_iot_channel.py`
  — including cross-device topic rejection and the identical results the
  HTTP and bus paths produce. Tests run without hardware or a broker.
- Safety: Phase 4 adds interlock/emergency-stop tests on the gateway stack.

## 8. Security & reliability roadmap hooks

| Requirement | Where it lands |
|---|---|
| Secure authentication, RBAC | Phase 1 (done) |
| Audit logs | Phase 1 (done) |
| Device authentication, encrypted comms (TLS/MQTT auth) | Phase 2 |
| Sensor failure detection | Phase 2 |
| Pump protection, leak detection, e-stop, hardware interlocks, offline control | Phase 4 |
| Backup & recovery, system configuration | Phase 6 |

---

## 9. Specification sources

Two prompts exist at the project root: `prompt.txt` (the 18-module
irrigation platform — the plan above) and `prompt2.txt` (a broader master
vision adding weed identification, chemical application/spraying safety,
farm security/intrusion detection, fire/lightning alerts and
harvest-maturity intelligence). This architecture implements `prompt.txt`
as the core program; the additional `prompt2` capabilities slot into the
existing phases as further module requirements rather than a separate plan:

- Weed ID + crop-protection chemicals → Phase 3 (knowledge/vision engine)
  and Phase 4 (application equipment with its own safety interlocks;
  chemical control follows the same "validated parameters only" rule).
- Farm security, intrusion/fire/lightning → Phase 2 (camera/sensor
  ingestion) + Phase 5 (alerting).
- Harvest maturity prediction → Phase 3 (crop knowledge) and Phase 6
  (prediction + learning loop).

The Phase 1 foundation (auth, RBAC, farms/zones, audit) serves both
specifications unchanged.
