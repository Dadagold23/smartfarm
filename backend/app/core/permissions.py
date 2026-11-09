"""RBAC permission catalog (Module 1).

Permission codes follow `resource.action[.scope]`. This catalog is the
single source of truth: `app.services.rbac_service.sync_rbac` materialises
it into the Role/Permission tables at startup / via Alembic seed, so the DB
and code can never drift apart, and later phases can extend roles without
schema changes.

Scope resolution rules used by services (documented in
docs/ARCHITECTURE.md):
  * `*.own` permissions authorise actions on resources the user owns.
  * `*.all`  permissions authorise the same actions on everyone's resources.
  * A holder of an `all` permission implicitly satisfies the `own` variant.
"""

# ---------------------------------------------------------------------------
# Permission codes
# ---------------------------------------------------------------------------

PERMISSIONS: dict[str, str] = {
    # Module 1 — users, roles
    "user.read": "View user accounts",
    "user.create": "Create user accounts",
    "user.update": "Update user accounts",
    "user.deactivate": "Deactivate user accounts",
    "role.read": "View roles and permissions",
    "role.manage": "Assign roles and edit role permissions",
    # Module 2 — farms and irrigation zones
    "farm.create": "Create farms",
    "farm.read.own": "Read own farms",
    "farm.read.all": "Read every farm (multi-farm oversight)",
    "farm.update.own": "Update own farms",
    "farm.update.all": "Update any farm",
    "farm.delete.own": "Delete own farms",
    "farm.delete.all": "Delete any farm",
    "zone.create": "Create irrigation zones on authorised farms",
    "zone.read": "Read irrigation zones on authorised farms",
    "zone.update": "Update irrigation zones on authorised farms",
    "zone.delete": "Delete irrigation zones on authorised farms",
    # Audit (cross-cutting security requirement)
    "audit.read": "Read audit logs",
    "audit.read.all": "Read audit logs of all users",
    # ------------------------------------------------------------------
    # Phase 2 — Modules 5/6/9: IoT devices, telemetry ingestion, soil +
    # weather data, sensor faults. Device/reading/fault ownership is
    # enforced through the parent farm (services re-check farm access), so
    # these are unscoped action gates; farm.read.own vs farm.read.all
    # decides which farms' data a caller sees. Device telemetry itself
    # authenticates with the device API key (see app.api.deps), not with
    # these user permissions; `telemetry.ingest` additionally lets a
    # farm manager push batches over the user-JWT path of the same
    # endpoints (manual backfill, simulator runs).
    "device.manage": "Register, update, rotate keys, revoke and list IoT devices on accessible farms",
    "telemetry.ingest": "Push device telemetry via the user-JWT path (device-key path uses the device API key)",
    "soil.read": "View soil probe telemetry on accessible farms",
    "weather.read": "View weather observations and forecasts on accessible farms",
    "faults.read": "View sensor failure (fault) events on accessible farms",
    # ------------------------------------------------------------------
    # Phase 3 — Agricultural intelligence (Modules 3, 4, 7, 12, 19, 22)
    # ------------------------------------------------------------------
    "crop.read": "View crop database, research parameters, and growth stages",
    "crop.manage": "Create, update, and delete crop species and growth stages",
    "crop.identify": "Submit images for AI crop identification and weed detection",
    "soil_profile.read": "View soil profiles and hydraulic properties",
    "soil_profile.manage": "Create, update, and delete soil profiles on accessible farms",
    "planting.read": "View planting batches, growth progress, and harvest predictions",
    "planting.manage": "Create, update, and manage planting batches and stages",
    "health.read": "View crop health assessments and stress records",
    "health.manage": "Record and update crop health assessments",
    "schedule.read": "View calculated irrigation schedules and scientific water balance",
    "schedule.manage": "Trigger calculation and approve or reject irrigation schedules",
    "advisory.generate": "Generate agronomic guidance for farm zones using live agronomic observations",
    "valve.control": "Start/stop irrigation valves and manage zone runtime state on accessible farms",
    "automation.manage": "Configure automatic irrigation programs and safety interlocks",
    "estop.trigger": "Trigger or clear emergency stop and disable unsafe irrigation flows",
    # ------------------------------------------------------------------
    # Phase 5: mobile.access, advisory.generate
    # Phase 6: settings.manage, backup.manage
    # ------------------------------------------------------------------
}

# ---------------------------------------------------------------------------
# Role catalog
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[str, dict[str, set[str]]] = {
    "admin": {
        "name": "Administrator",
        "description": "Full system control, multi-farm oversight and audit access.",
        "permissions": {
            "user.read", "user.create", "user.update", "user.deactivate",
            "role.read", "role.manage",
            "farm.create", "farm.read.all", "farm.update.all", "farm.delete.all",
            "zone.create", "zone.read", "zone.update", "zone.delete",
            "device.manage", "telemetry.ingest",
            "soil.read", "weather.read", "faults.read",
            "crop.read", "crop.manage", "crop.identify",
            "soil_profile.read", "soil_profile.manage",
            "planting.read", "planting.manage",
            "health.read", "health.manage",
            "schedule.read", "schedule.manage",
            "advisory.generate",
            "valve.control", "automation.manage", "estop.trigger",
            "audit.read", "audit.read.all",
        },
    },
    "farm_manager": {
        "name": "Farm Manager",
        "description": "Owns and manages their farms, zones and field devices.",
        "permissions": {
            "farm.create", "farm.read.own", "farm.update.own", "farm.delete.own",
            "zone.create", "zone.read", "zone.update", "zone.delete",
            "device.manage", "telemetry.ingest",
            "soil.read", "weather.read", "faults.read",
            "crop.read", "crop.manage", "crop.identify",
            "soil_profile.read", "soil_profile.manage",
            "planting.read", "planting.manage",
            "health.read", "health.manage",
            "schedule.read", "schedule.manage",
            "advisory.generate",
            "valve.control", "automation.manage", "estop.trigger",
            "audit.read",
            # NOTE: farm_manager does NOT get user.read — account management
            # is an admin concern; registration is public.
        },
    },
    "operator": {
        "name": "Field Operator",
        "description": "Reads assigned farms/zones/telemetry; later phases add valve control.",
        "permissions": {
            "farm.read.own",
            "zone.read",
            "soil.read", "weather.read", "faults.read",
            "crop.read", "crop.identify",
            "soil_profile.read",
            "planting.read",
            "health.read", "health.manage",
            "schedule.read",
            "valve.control", "estop.trigger",
        },
    },
    "advisor": {
        "name": "Agricultural Advisor",
        "description": "Read-only across all farms for agronomy advisory.",
        "permissions": {
            "farm.read.all",
            "zone.read",
            "soil.read", "weather.read", "faults.read",
            "crop.read", "crop.identify",
            "soil_profile.read",
            "planting.read",
            "health.read", "health.manage",
            "schedule.read", "schedule.manage",
            "advisory.generate",
        },
    },
    "viewer": {
        "name": "Viewer",
        "description": "Minimal read-only access to own farms and telemetry.",
        "permissions": {
            "farm.read.own",
            "soil.read", "weather.read",
            "crop.read", "soil_profile.read", "planting.read", "health.read", "schedule.read",
        },
    },
}

DEFAULT_ROLE_CODE = "farm_manager"


def satisfies(required: str, held: set[str]) -> bool:
    """True if the held permission set satisfies `required` (own/all rule)."""
    if required in held:
        return True
    if required.endswith(".own"):
        return required[: -len(".own")] + ".all" in held
    return False
