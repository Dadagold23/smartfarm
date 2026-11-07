"""Transport-agnostic MQTT telemetry handler — the SINGLE ingestion core
shared by the real paho-mqtt subscriber and the in-process fallback bus.

Flow for one message (identical on both transports):

  1. topic must match the schema (app/iot/topics.py)            -> invalid_topic
  2. device-key authentication: the key presented with the
     message (bus CONNECT-style credentials, or an optional
     payload "device_key" field) must resolve to a registered
     ACTIVE device                                        -> auth_failed
  3. topic-binding authorisation: that device must BE the
     (farm_id, device_code) the topic names — device A can
     never publish into device B's topic                   -> topic_not_authorized
  4. payload JSON = one reading / list of readings / {"readings": [...]}
     with per-reading shape IDENTICAL to SoilTelemetryIn /
     WeatherTelemetryIn; the TOPIC kind selects the schema -> invalid_payload
  5. readings go through `telemetry_service.ingest_*_batch`
     with `source='mqtt'` — the same validation, idempotent
     (device, measured_at) dedupe and fault engine as HTTP.

An auth failure attributable to a real device raises the existing
`auth_failure` fault type (audited through the fault engine).
"""

import json
import logging
from typing import Callable

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError
from app.iot.bus import BusCredentials, BusMessage
from app.iot.topics import TopicError, parse_topic
from app.models.iot import Device, DeviceType, FaultType
from app.schemas.iot import SoilTelemetryIn, WeatherTelemetryIn
from app.services import device_service, telemetry_service

logger = logging.getLogger("asiis.iot.handler")

_READING_MODELS = {"soil": SoilTelemetryIn, "weather": WeatherTelemetryIn}

# device types allowed to carry each telemetry kind (combined stations carry
# both; gateways aggregate for their devices over the same channel contract).
_KIND_DEVICE_TYPES = {
    "soil": {DeviceType.soil_probe, DeviceType.combined_station,
             DeviceType.gateway, DeviceType.other},
    "weather": {DeviceType.weather_station, DeviceType.combined_station,
                DeviceType.gateway, DeviceType.other},
}


def _result(ok: bool, status: str, **extra) -> dict:
    return {"ok": ok, "status": status, **extra}


def process_telemetry_message(
    db: Session, *, topic: str, payload: str | bytes,
    credentials: BusCredentials | None = None,
    base_topic: str,
) -> dict:
    """Handle one published message; returns a JSON-serialisable result
    dict. Never raises for bad input — a broker subscriber cannot NACK, so
    rejection is signalled in the result and logged."""
    creds = credentials or BusCredentials()

    # 1. topic schema
    try:
        parsed = parse_topic(topic, base_topic)
    except TopicError as exc:
        logger.warning("rejected message on malformed topic %r: %s", topic, exc)
        return _result(False, "invalid_topic", error=str(exc))

    # payload JSON (needed before auth: may carry device_key)
    try:
        body = json.loads(payload.decode("utf-8") if isinstance(payload, bytes)
                          else payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _result(False, "invalid_payload",
                       error=f"payload is not UTF-8 JSON: {exc}")

    presented_key = creds.password
    device_key_in_payload = False
    if isinstance(body, dict) and isinstance(body.get("device_key"), str):
        presented_key = body["device_key"]
        body = {k: v for k, v in body.items() if k != "device_key"}
        device_key_in_payload = True

    # 2/3. device authentication + topic binding
    device: Device | None = None
    try:
        device = device_service.authenticate_device_key(db, presented_key)
    except AuthenticationError as exc:
        _maybe_flag_auth_failure(db, topic, parsed, str(exc))
        return _result(False, "auth_failed", error=str(exc),
                       topic_farm_id=parsed.farm_id,
                       topic_device_code=parsed.device_code,
                       device_key_in_payload=device_key_in_payload)
    if device.farm_id != parsed.farm_id or device.code != parsed.device_code:
        _maybe_flag_auth_failure(
            db, topic, parsed,
            "presented key belongs to another device")
        return _result(False, "topic_not_authorized",
                       error="device key does not match the topic",
                       topic_farm_id=parsed.farm_id,
                       topic_device_code=parsed.device_code,
                       authenticated_device_id=device.id)

    if parsed.kind not in _KIND_DEVICE_TYPES or device.device_type not in _KIND_DEVICE_TYPES[parsed.kind]:
        _maybe_flag_auth_failure(
            db, topic, parsed,
            f"device type {device.device_type.value} may not publish {parsed.kind}")
        return _result(False, "topic_not_authorized",
                       error=f"device type {device.device_type.value} is not "
                             f"registered to publish {parsed.kind} telemetry",
                       topic_farm_id=parsed.farm_id,
                       topic_device_code=parsed.device_code,
                       authenticated_device_id=device.id)

    # 4. per-reading validation — schema chosen by the TOPIC kind
    if isinstance(body, list):
        raw_items = body
    elif isinstance(body, dict) and isinstance(body.get("readings"), list):
        raw_items = body["readings"]
    elif isinstance(body, dict):
        raw_items = [body]
    else:
        raw_items = None
    if raw_items is None:
        return _result(False, "invalid_payload",
                       error="payload must be a reading object, a list of "
                             "reading objects, or {'readings': [...]}")
    model = _READING_MODELS[parsed.kind]
    try:
        readings = [model.model_validate(item) for item in raw_items]
    except (PydanticValidationError, ValueError) as exc:
        return _result(False, "invalid_payload",
                       error=f"reading failed {model.__name__} validation: {exc}",
                       device_id=device.id)
    if not readings:
        return _result(False, "invalid_payload", error="no readings in message",
                       device_id=device.id)

    # A device that authenticates cleanly again clears any open auth_failure.
    telemetry_service.resolve_fault(
        db, device, FaultType.auth_failure, device_service.utcnow_naive())

    # 5. SAME pipeline as HTTP, flagged with mqtt provenance
    ingest_fn = (
        telemetry_service.ingest_soil_batch if parsed.kind == "soil"
        else telemetry_service.ingest_weather_batch
    )
    summary = ingest_fn(
        db, device, readings,
        actor_label=f"mqtt:{device.code}",
        ip_address="",  # broker-local; the broker logs the publisher IP
        source="mqtt",
    )
    # summary already carries device_id/batch_id/accepted/…
    return _result(True, "processed", kind=parsed.kind, **summary)


def _maybe_flag_auth_failure(db: Session, topic: str, parsed, reason: str) -> None:
    """If the topic names a real registered device, record an auth_failure
    fault (create-once/audited via the shared fault engine)."""
    try:
        device = (
            db.query(Device)
            .filter(Device.farm_id == parsed.farm_id,
                    Device.code == parsed.device_code,
                    Device.is_deleted.is_(False))
            .first()
        )
        if device is None:
            return
        now = device_service.utcnow_naive()
        telemetry_service.raise_fault(
            db, device, FaultType.auth_failure,
            f"telemetry rejected on {topic}: {reason}",
            {"topic": topic, "reason": reason}, now,
        )
        db.commit()
    except Exception:  # noqa: BLE001 — fault recording must never mask the reject
        logger.exception("failed to record auth_failure for topic %s", topic)
        db.rollback()


def make_bus_subscriber(session_factory, base_topic: str) -> Callable[[BusMessage], dict]:
    """Adapter registering the handler on the in-process fallback bus.

    Each message runs on a fresh session from `session_factory` (mirrors the
    per-message session a long-lived broker subscriber uses), so results are
    committed through the normal pipeline.
    """
    def _on_message(msg: BusMessage) -> dict:
        with session_factory() as db:
            return process_telemetry_message(
                db, topic=msg.topic, payload=msg.payload,
                credentials=msg.credentials, base_topic=base_topic,
            )

    return _on_message
