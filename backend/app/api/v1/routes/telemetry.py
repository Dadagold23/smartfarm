"""Phase 2 — device-authenticated telemetry ingestion endpoints.

Auth is INDEPENDENT of the user JWT: a device presents its API key in the
`X-Device-Key` header (registered/rotated via /devices). A human may also
push batches over the same endpoints using a Bearer token + the
`telemetry.ingest` permission, naming the target device explicitly —
this is the manual-backfill / simulator-upload path, not a mock.

Batches are processed item-by-item: replays are deduped idempotently on
(device, measured_at), implausible timestamps are rejected per item, and
each request refreshes device liveness + fault state (see
app/services/telemetry_service.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import (
    DbSession,
    IngestIdentity,
    client_ip,
    resolve_ingest_identity,
)
from app.core.exceptions import PermissionDeniedError, ValidationError
from app.schemas.iot import (
    SoilTelemetryBatchIn,
    TelemetryBatchMeta,
    WeatherTelemetryBatchIn,
)
from app.services import device_service, telemetry_service

router = APIRouter()

IngestAuth = Annotated[IngestIdentity, Depends(resolve_ingest_identity)]


def _resolve_target_device(db, identity: IngestIdentity, body):
    """Device-key path: implicitly its own device (no device_id override).
    User-JWT path: device_id required and must be manageable by the caller."""
    if identity.device is not None:
        if body.device_id is not None and body.device_id != identity.device.id:
            raise ValidationError(
                "device-key uploads cannot target another device"
            )
        return identity.device
    if body.device_id is None:
        raise ValidationError("device_id is required for user-JWT uploads")
    return device_service.get_accessible_device(
        db, body.device_id, identity.user, identity.held, "manage"
    )


def _ingest(db, request: Request, identity: IngestIdentity, body, *, model: str):
    device = _resolve_target_device(db, identity, body)
    if device.status.value != "active":
        # Revoked devices must not store data even on the human path.
        raise PermissionDeniedError("device credentials revoked")
    ingest_fn = (
        telemetry_service.ingest_soil_batch if model == "soil"
        else telemetry_service.ingest_weather_batch
    )
    result = ingest_fn(
        db, device, body.readings, actor_label=identity.actor_label,
        ip_address=client_ip(request),
        user_id=identity.user.id if identity.user else None,
    )
    return TelemetryBatchMeta.model_validate(result)


@router.post("/soil", response_model=TelemetryBatchMeta)
def ingest_soil(
    body: SoilTelemetryBatchIn,
    request: Request,
    db: DbSession,
    identity: IngestAuth,
):
    return _ingest(db, request, identity, body, model="soil")


@router.post("/weather", response_model=TelemetryBatchMeta)
def ingest_weather(
    body: WeatherTelemetryBatchIn,
    request: Request,
    db: DbSession,
    identity: IngestAuth,
):
    return _ingest(db, request, identity, body, model="weather")
