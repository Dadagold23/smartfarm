"""Phase 2 — sensor fault endpoints (faults.read).

GET /faults runs the lightweight staleness sweep first (open/close
stale_data events from current last_seen values), so the listing is live
without a scheduler; out-of-range/flatline events are maintained at
ingestion time. Farm ownership scoping happens in device_service.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, require_permissions
from app.schemas.iot import FaultOut
from app.services import device_service, telemetry_service

router = APIRouter()

RequiresFaultsRead = Annotated[set[str], Depends(require_permissions("faults.read"))]


@router.get("", response_model=dict)
def list_faults(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresFaultsRead,
    farm_id: int | None = None,
    device_id: int | None = None,
    open_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: int = Query(0, ge=0),
):
    telemetry_service.scan_stale(db)
    db.commit()
    items, total = device_service.list_faults(
        db, current_user, held, farm_id=farm_id, device_id=device_id,
        open_only=open_only, limit=limit, offset=offset,
    )
    return {
        "items": [FaultOut.model_validate(f).model_dump(mode="json") for f in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }
