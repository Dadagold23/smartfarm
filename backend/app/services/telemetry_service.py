"""Phase 2 (Modules 5/6/9) — telemetry ingestion + sensor failure detection.

Single pipeline used by every transport (HTTP now, MQTT in the next run):
`ingest_soil_batch` / `ingest_weather_batch` take a device authenticated by
its API key (or a JWT user holding `telemetry.ingest`) and per reading:

  1. reject implausible timestamps (future beyond TELEMETRY_MAX_FUTURE_SKEW),
  2. dedupe idempotently on (device_id, measured_at) — a replayed message is
     reported as `duplicate`, never double-stored,
  3. store the reading WITH provenance (`is_simulated`, source, raw payload,
     batch id) even when quality-flagged (evidence is kept, flagged, and
     alerted — never silently dropped),
  4. advance `device.last_seen_at`,
  5. re-evaluate the device's fault conditions.

Fault model — one OPEN event per (device, fault_type):
  * STALE: no accepted reading for TELEMETRY_STALE_MINUTES (also computed by
    `scan_stale`, run before GET /faults so the list is always current).
  * OUT_OF_RANGE: a metric outside sensor *operating* limits. Defaults below
    are hardware specification bounds (e.g. -40..85 °C component range,
    solar irradiance cannot exceed the ~1361 W/m2 solar constant); they are
    evidence of device malfunction, NOT agronomic thresholds, and can be
    overridden per deployment via TELEMETRY_OPERATING_RANGES (env JSON).
  * FLATLINE: FLATLINE_CONSECUTIVE_READINGS identical consecutive values of
    one metric — the classic stuck-sensor signature.
Events are created-once, refreshed while open, resolved when the condition
clears, and every transition is mirrored to the audit log.
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.core.permissions import satisfies
from app.models.farm import Farm
from app.models.iot import Device, DeviceFaultEvent, DeviceStatus, FaultType
from app.models.soil import SoilReading
from app.models.user import User
from app.models.weather import WeatherForecast, WeatherObservation
from app.services import audit_service, device_service, farm_service

# ---------------------------------------------------------------------------
# Operating ranges (hardware spec bounds) — metric keys are
# "<kind>.<field>"; kind soil = soil probe metrics, wx = weather station.
# ---------------------------------------------------------------------------

DEFAULT_OPERATING_RANGES: dict[str, list[float]] = {
    # Volumetric water content: probes report 0-100%; >65% in-field sustained
    # means saturated slurry / suspect probe. Broad fault bound, not agronomy.
    "soil.moisture_pct": [0.0, 65.0],
    # Typical commercial soil probe operating temperature (e.g. -15..60 °C).
    "soil.temperature_c": [-15.0, 60.0],
    # EC: commercial probes saturate near 200 mS/cm; values above 20 mS/cm in
    # soil solution are extremely saline — flag as suspect, do not reject.
    "soil.ec_mS_cm": [0.0, 20.0],
    # Component junction/environmental spec range of weather stations.
    "wx.temperature_c": [-40.0, 85.0],
    "wx.humidity_pct": [0.0, 100.0],
    # Wind: cup anemometers are rated far below hurricanes; 75 m/s is the
    # practical instrument spec ceiling (destructive beyond).
    "wx.wind_speed_m_s": [0.0, 75.0],
    "wx.wind_direction_deg": [0.0, 360.0],
    # Physical ceiling: solar constant ~1361 W/m2 (above atmosphere).
    "wx.solar_radiation_w_m2": [0.0, 1361.0],
    # Rain gauges: small negative values are tipping-bucket noise; >500 mm
    # per report interval exceeds any recorded event for one observation.
    "wx.rainfall_mm": [-0.5, 500.0],
    # Barometric pressure at Earth's surface (record extremes ~870/1084 hPa).
    "wx.pressure_hpa": [850.0, 1100.0],
}

SOIL_METRICS = ("moisture_pct", "temperature_c", "ec_mS_cm")
WX_METRICS = (
    "temperature_c", "humidity_pct", "wind_speed_m_s", "wind_direction_deg",
    "solar_radiation_w_m2", "rainfall_mm", "pressure_hpa",
)

# pipeline model name -> operating-range key prefix
_RANGE_KIND = {"soil": "soil", "weather": "wx"}


def operating_ranges() -> dict[str, list[float]]:
    ranges = dict(DEFAULT_OPERATING_RANGES)
    overrides = get_settings().TELEMETRY_OPERATING_RANGES or {}
    for key, bounds in overrides.items():
        if isinstance(bounds, list) and len(bounds) == 2:
            ranges[key] = [float(bounds[0]), float(bounds[1])]
    return ranges


# ---------------------------------------------------------------------------
# Fault lifecycle helpers (create-once / refresh / resolve)
# ---------------------------------------------------------------------------

def _fault_open(db: Session, device_id: int, fault_type: FaultType):
    return (
        db.query(DeviceFaultEvent)
        .filter(DeviceFaultEvent.device_id == device_id,
                DeviceFaultEvent.fault_type == fault_type,
                DeviceFaultEvent.open_marker == 1)
        .first()
    )


def raise_fault(
    db: Session, device: Device, fault_type: FaultType, message: str,
    details: dict, now: datetime,
) -> tuple[DeviceFaultEvent, bool]:
    """Create the open event or refresh the existing one. Returns
    (event, created_new). New/refreshed events are audited once at creation."""
    event = _fault_open(db, device.id, fault_type)
    if event is not None:
        event.message = message[:2000]
        event.details_json = json.dumps(details, default=str)
        return event, False
    event = DeviceFaultEvent(
        device_id=device.id, farm_id=device.farm_id, fault_type=fault_type,
        message=message[:2000], details_json=json.dumps(details, default=str),
        detected_at=now, open_marker=1,
    )
    db.add(event)
    db.flush()
    audit_service.log(
        db, user_id=None, actor_label="system", action="fault.detected",
        resource_type="device_fault_event", resource_id=event.id,
        details={"device_id": device.id, "farm_id": device.farm_id,
                 "fault_type": fault_type.value, "message": event.message},
    )
    return event, True


def resolve_fault(
    db: Session, device: Device, fault_type: FaultType, now: datetime,
) -> DeviceFaultEvent | None:
    event = _fault_open(db, device.id, fault_type)
    if event is None:
        return None
    event.resolved_at = now
    event.open_marker = None
    audit_service.log(
        db, user_id=None, actor_label="system", action="fault.resolved",
        resource_type="device_fault_event", resource_id=event.id,
        details={"device_id": device.id, "fault_type": fault_type.value},
    )
    return event


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def _out_of_range_metrics(model: str, values: dict) -> list[str]:
    ranges = operating_ranges()
    kind = _RANGE_KIND[model]
    flagged = []
    for metric, value in values.items():
        if value is None:
            continue
        bounds = ranges.get(f"{kind}.{metric}")
        if bounds and not (bounds[0] <= float(value) <= bounds[1]):
            flagged.append(metric)
    return flagged


def _flatlined_metrics(db: Session, device: Device, model: str,
                      metrics: tuple[str, ...], current: dict,
                      exclude_measured_at: datetime | None = None) -> list[str]:
    """Metric is flatlined when the new value plus the previous
    FLATLINE_CONSECUTIVE_READINGS-1 accepted readings are all identical.

    `exclude_measured_at` skips the row that IS the new value when it has
    already been flushed to the table (post-insert re-evaluation), so the
    "N consecutive" rule counts true history in both call contexts.
    """
    n = get_settings().FLATLINE_CONSECUTIVE_READINGS
    if n < 2:
        return []
    model_cls = SoilReading if model == "soil" else WeatherObservation
    flat = []
    for metric in metrics:
        if current.get(metric) is None:
            continue
        q = (
            db.query(getattr(model_cls, metric))
            .filter(model_cls.device_id == device.id,
                    getattr(model_cls, metric).isnot(None))
        )
        if exclude_measured_at is not None:
            q = q.filter(model_cls.measured_at != exclude_measured_at)
        prev_values = q.order_by(model_cls.measured_at.desc()).limit(n - 1).all()
        if len(prev_values) < n - 1:
            continue
        new_val = Decimal(str(current[metric]))
        if all(v[0] == new_val for v in prev_values):
            flat.append(metric)
    return flat


def _reevaluate_quality_faults(
    db: Session, device: Device, model: str, now: datetime,
) -> list[DeviceFaultEvent]:
    """Out-of-range / flatline state is derived from the device's latest
    accepted reading; called after every ingestion."""
    model_cls = SoilReading if model == "soil" else WeatherObservation
    metrics = SOIL_METRICS if model == "soil" else WX_METRICS
    latest = (
        db.query(model_cls)
        .filter(model_cls.device_id == device.id)
        .order_by(model_cls.measured_at.desc())
        .first()
    )
    touched: list[DeviceFaultEvent] = []
    if latest is None:
        return touched
    current = {m: getattr(latest, m) for m in metrics}

    bad = _out_of_range_metrics(model, current)
    if bad:
        event, _ = raise_fault(
            db, device, FaultType.out_of_range,
            f"latest reading(s) outside sensor operating range: {', '.join(bad)}",
            {"metrics": bad, "measured_at": latest.measured_at,
             "values": {m: str(current[m]) for m in bad}},
            now,
        )
        touched.append(event)
    else:
        resolved = resolve_fault(db, device, FaultType.out_of_range, now)
        if resolved:
            touched.append(resolved)

    flat = _flatlined_metrics(db, device, model, metrics, current,
                              exclude_measured_at=latest.measured_at)
    if flat:
        n = get_settings().FLATLINE_CONSECUTIVE_READINGS
        event, _ = raise_fault(
            db, device, FaultType.flatline,
            f"{n}+ consecutive identical values for: {', '.join(flat)} "
            "(sensor suspected stuck)",
            {"metrics": flat,
             "values": {m: str(current[m]) for m in flat}},
            now,
        )
        touched.append(event)
    else:
        resolved = resolve_fault(db, device, FaultType.flatline, now)
        if resolved:
            touched.append(resolved)
    return touched


def scan_stale(db: Session, now: datetime | None = None,
               device_ids: list[int] | None = None) -> list[DeviceFaultEvent]:
    """Lightweight staleness sweep (called before GET /faults so listings
    are live without a scheduler). O(active devices), indexed read."""
    now = now or device_service.utcnow_naive()
    q = db.query(Device).filter(
        Device.is_deleted.is_(False), Device.status == DeviceStatus.active
    )
    if device_ids is not None:
        q = q.filter(Device.id.in_(device_ids))
    touched: list[DeviceFaultEvent] = []
    for device in q.all():
        if device_service.is_device_stale(device, now):
            ref = device.last_seen_at or device.created_at
            minutes = int((now - ref).total_seconds() // 60)
            event, _ = raise_fault(
                db, device, FaultType.stale_data,
                f"no accepted telemetry for {minutes} min "
                f"(threshold {get_settings().TELEMETRY_STALE_MINUTES} min)",
                {"last_seen_at": ref, "minutes_since": minutes},
                now,
            )
            touched.append(event)
        else:
            resolved = resolve_fault(db, device, FaultType.stale_data, now)
            if resolved:
                touched.append(resolved)
    return touched


# ---------------------------------------------------------------------------
# Ingestion pipeline (transport-agnostic; MQTT run reuses these)
# ---------------------------------------------------------------------------

def _reject_future(measured_at: datetime, now: datetime) -> bool:
    skew = get_settings().TELEMETRY_MAX_FUTURE_SKEW_MINUTES
    return measured_at > now + timedelta(minutes=skew)


def _touch_device(device: Device, now: datetime) -> None:
    if device.last_seen_at is None or device.last_seen_at < now:
        device.last_seen_at = now


def _ingest_batch(
    db: Session, device: Device, readings, *, model: str,
    actor_label: str, ip_address: str, user_id: int | None,
    source: str = "device",
) -> dict:
    """Shared soil/weather ingestion. Commits once per batch.

    `source` records the transport provenance ('device' = HTTP device-key /
    user-JWT endpoint, 'mqtt' = MQTT channel incl. the in-process fallback
    bus); it must be a ReadingSource/ObservationSource value.
    """
    settings = get_settings()
    if len(readings) > settings.TELEMETRY_MAX_BATCH:
        raise ValidationError(
            f"batch size {len(readings)} exceeds TELEMETRY_MAX_BATCH="
            f"{settings.TELEMETRY_MAX_BATCH}"
        )
    now = device_service.utcnow_naive()
    batch_id = _new_batch_id()
    model_cls = SoilReading if model == "soil" else WeatherObservation
    metrics = SOIL_METRICS if model == "soil" else WX_METRICS

    results = []
    accepted = duplicates = rejected = 0
    for item in readings:
        values = {m: getattr(item, m) for m in metrics}
        if _reject_future(item.measured_at, now):
            rejected += 1
            results.append({
                "ok": False, "status": "rejected",
                "measured_at": item.measured_at,
                "error": "measured_at is in the future beyond allowed clock skew",
            })
            continue

        existing = (
            db.query(model_cls)
            .filter(model_cls.device_id == device.id,
                    model_cls.measured_at == item.measured_at)
            .first()
        )
        if existing is not None:
            # Idempotent replay: counted, never double-stored. The device IS
            # heard from, so liveness still advances.
            _touch_device(device, now)
            duplicates += 1
            results.append({
                "ok": True, "status": "duplicate",
                "reading_id": existing.id, "measured_at": item.measured_at,
                "quality_flags": json.loads(existing.quality_flags or "[]"),
                "is_simulated": existing.is_simulated,
            })
            continue

        flags = _out_of_range_metrics(model, values)
        if _flatlined_metrics(db, device, model, metrics, values):
            flags.append("flatline")

        row_kwargs = dict(
            device_id=device.id, farm_id=device.farm_id,
            measured_at=item.measured_at,
            quality_flags=json.dumps(flags),
            is_simulated=bool(item.simulated),
            source=_source_for(device, source),
            raw_payload=json.dumps(item.model_dump(mode="json"), default=str),
            ingest_batch_id=batch_id,
        )
        if model == "soil":
            # zone denormalisation exists on soil readings; weather
            # stations are farm-level assets (no zone_id column).
            row_kwargs["zone_id"] = device.zone_id
            row_kwargs["probe_depth_cm"] = item.probe_depth_cm
        row = model_cls(**row_kwargs)
        for metric in metrics:
            setattr(row, metric, values[metric])
        db.add(row)
        try:
            # SAVEPOINT: a replay race rolls back only this row, keeping
            # the rest of the batch's work (rollback() would nuke it all).
            with db.begin_nested():
                db.flush()
        except IntegrityError:  # concurrent replay race — dedupe backstop
            existing = (
                db.query(model_cls)
                .filter(model_cls.device_id == device.id,
                        model_cls.measured_at == item.measured_at)
                .first()
            )
            _touch_device(device, now)
            duplicates += 1
            results.append({
                "ok": True, "status": "duplicate",
                "reading_id": existing.id if existing else None,
                "measured_at": item.measured_at,
            })
            continue
        _touch_device(device, now)
        accepted += 1
        results.append({
            "ok": True, "status": "accepted", "reading_id": row.id,
            "measured_at": item.measured_at, "quality_flags": flags,
            "is_simulated": row.is_simulated,
        })

    fault_events = _reevaluate_quality_faults(db, device, model, now)
    # A device that just spoke is no longer stale; keep STALE live immediately.
    if device_service.is_device_stale(device, now):
        ref = device.last_seen_at or device.created_at
        minutes = int((now - ref).total_seconds() // 60)
        raise_fault(db, device, FaultType.stale_data,
                    f"no accepted telemetry for {minutes} min",
                    {"last_seen_at": ref, "minutes_since": minutes}, now)
    else:
        resolve_fault(db, device, FaultType.stale_data, now)

    audit_service.log(
        db, user_id=user_id, actor_label=actor_label,
        action=f"telemetry.ingest.{model}", resource_type="device",
        resource_id=device.id,
        details={"batch_id": batch_id, "accepted": accepted,
                 "duplicates": duplicates, "rejected": rejected},
        ip_address=ip_address,
    )
    db.commit()

    open_faults = device_service.open_faults_for(db, device.id)
    fault_payload = [_fault_dict(e) for e in open_faults]
    for r in results:
        r.setdefault("faults", fault_payload if accepted else [])
    return {
        "device_id": device.id, "batch_id": batch_id,
        "accepted": accepted, "duplicates": duplicates, "rejected": rejected,
        "results": results,
    }


def _source_for(device: Device, source: str = "device") -> str:
    """Transport provenance for stored rows. The HTTP endpoints keep the
    default 'device'; the MQTT channel (app/iot/handler.py) passes 'mqtt',
    so every reading records HOW it arrived, not just from where."""
    return source


def _new_batch_id() -> str:
    import uuid
    return uuid.uuid4().hex


def ingest_soil_batch(db: Session, device: Device, readings, *,
                      actor_label: str, ip_address: str = "",
                      user_id: int | None = None,
                      source: str = "device") -> dict:
    return _ingest_batch(db, device, readings, model="soil",
                         actor_label=actor_label, ip_address=ip_address,
                         user_id=user_id, source=source)


def ingest_weather_batch(db: Session, device: Device, readings, *,
                         actor_label: str, ip_address: str = "",
                         user_id: int | None = None,
                         source: str = "device") -> dict:
    return _ingest_batch(db, device, readings, model="weather",
                         actor_label=actor_label, ip_address=ip_address,
                         user_id=user_id, source=source)


def _fault_dict(event: DeviceFaultEvent) -> dict:
    return {
        "id": event.id, "device_id": event.device_id, "farm_id": event.farm_id,
        "fault_type": event.fault_type, "message": event.message,
        "details_json": event.details_json, "detected_at": event.detected_at,
        "resolved_at": event.resolved_at,
    }


# ---------------------------------------------------------------------------
# Farm-scoped reads (soil / weather / forecasts)
# ---------------------------------------------------------------------------

def _visible_farm_ids(db: Session, user: User, held: set[str],
                      farm_id: int | None) -> list[int] | None:
    """None = no restriction (farm.read.all). Ownership scoped otherwise."""
    if farm_id is not None:
        farm_service.get_accessible_farm(db, farm_id, user, "read", held)
        return [farm_id]
    if satisfies("farm.read.all", held):
        return None
    rows = (
        db.query(Farm.id)
        .filter(Farm.is_deleted.is_(False), Farm.owner_id == user.id)
        .all()
    )
    return [r[0] for r in rows]


def _history_query(db: Session, model_cls, farm_ids, device_id, start, end,
                   limit, offset):
    q = db.query(model_cls)
    if farm_ids is not None:
        q = q.filter(model_cls.farm_id.in_(farm_ids))
    if device_id is not None:
        q = q.filter(model_cls.device_id == device_id)
    if start is not None:
        q = q.filter(model_cls.measured_at >= start)
    if end is not None:
        q = q.filter(model_cls.measured_at <= end)
    total = q.count()
    items = (
        q.order_by(model_cls.measured_at.desc(), model_cls.id.desc())
        .limit(limit).offset(offset).all()
    )
    return items, total


def list_soil_history(db: Session, user: User, held: set[str], *, farm_id,
                      device_id, start, end, limit, offset):
    return _history_query(db, SoilReading,
                          _visible_farm_ids(db, user, held, farm_id),
                          device_id, start, end, limit, offset)


def list_weather_history(db: Session, user: User, held: set[str], *, farm_id,
                        device_id, start, end, limit, offset):
    return _history_query(db, WeatherObservation,
                          _visible_farm_ids(db, user, held, farm_id),
                          device_id, start, end, limit, offset)


def _latest_per_device(db: Session, model_cls, farm_ids):
    sub = (
        db.query(model_cls.device_id.label("device_id"),
                 func.max(model_cls.measured_at).label("max_at"))
        .group_by(model_cls.device_id)
        .subquery()
    )
    q = (
        db.query(model_cls)
        .join(sub, (model_cls.device_id == sub.c.device_id)
                  & (model_cls.measured_at == sub.c.max_at))
    )
    if farm_ids is not None:
        q = q.filter(model_cls.farm_id.in_(farm_ids))
    return q.order_by(model_cls.farm_id, model_cls.device_id).all()


def list_soil_latest(db: Session, user: User, held: set[str], farm_id):
    return _latest_per_device(db, SoilReading,
                              _visible_farm_ids(db, user, held, farm_id))


def list_weather_latest(db: Session, user: User, held: set[str], farm_id):
    return _latest_per_device(db, WeatherObservation,
                              _visible_farm_ids(db, user, held, farm_id))


def list_forecasts(db: Session, user: User, held: set[str], *, farm_id,
                   days: int | None, limit, offset):
    """Stored provider forecasts, most recent issue per farm. Forecast
    WRITING (provider adapters) lands with the simulator/providers run;
    this read path returns only real persisted rows."""
    farm_ids = _visible_farm_ids(db, user, held, farm_id)
    latest_issue = (
        db.query(WeatherForecast.farm_id.label("farm_id"),
                 func.max(WeatherForecast.issued_at).label("max_issued"))
        .group_by(WeatherForecast.farm_id)
        .subquery()
    )
    q = (
        db.query(WeatherForecast)
        .join(latest_issue,
              (WeatherForecast.farm_id == latest_issue.c.farm_id)
              & (WeatherForecast.issued_at == latest_issue.c.max_issued))
    )
    if farm_ids is not None:
        q = q.filter(WeatherForecast.farm_id.in_(farm_ids))
    if days is not None:
        q = q.filter(WeatherForecast.lead_time_days <= days)
    total = q.count()
    items = (
        q.order_by(WeatherForecast.farm_id,
                   WeatherForecast.forecast_date)
        .limit(limit).offset(offset).all()
    )
    return items, total
