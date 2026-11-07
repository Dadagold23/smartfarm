"""Module 5 — soil telemetry read endpoints (soil.read, farm-scoped).

Every payload carries provenance: `is_simulated` (spec-sanctioned sensor
simulator data, badged so it is never presented as measured), `source`
(device HTTP vs future MQTT) and per-reading `quality_flags` — the future
UI badges these directly.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, require_permissions
from app.schemas.iot import SoilReadingOut
from app.services import telemetry_service

router = APIRouter()

RequiresSoilRead = Annotated[set[str], Depends(require_permissions("soil.read"))]


@router.get("/latest", response_model=dict)
def soil_latest(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresSoilRead,
    farm_id: int | None = None,
):
    items = telemetry_service.list_soil_latest(db, current_user, held, farm_id)
    return {"items": [SoilReadingOut.model_validate(r) for r in items]}


@router.get("/history", response_model=dict)
def soil_history(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresSoilRead,
    farm_id: int | None = None,
    device_id: int | None = None,
    start: datetime | None = Query(default=None, description="naive UTC"),
    end: datetime | None = Query(default=None, description="naive UTC"),
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: int = Query(0, ge=0),
):
    items, total = telemetry_service.list_soil_history(
        db, current_user, held, farm_id=farm_id, device_id=device_id,
        start=start, end=end, limit=limit, offset=offset,
    )
    return {
        "items": [SoilReadingOut.model_validate(r).model_dump(mode="json") for r in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }
