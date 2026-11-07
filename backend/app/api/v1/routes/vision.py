"""Modules 3 & 19 — AI Plant Identification and Weed Detection endpoints."""

import base64
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.core.exceptions import ValidationError
from app.schemas.vision import (
    PlantIdentificationListOut,
    PlantIdentificationOut,
    PlantIdentificationVerifyIn,
)
from app.services import farm_service
from app.services.vision import plant_identifier

router = APIRouter()

RequiresCropIdentify = Annotated[set[str], Depends(require_permissions("crop.identify"))]
RequiresCropRead = Annotated[set[str], Depends(require_permissions("crop.read"))]
RequiresCropManage = Annotated[set[str], Depends(require_permissions("crop.manage"))]


@router.post("/identify", response_model=PlantIdentificationOut, status_code=201)
async def identify_plant(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresCropIdentify,
    file: UploadFile = File(...),
    farm_id: int | None = Form(None),
    zone_id: int | None = Form(None),
    hint_crop_id: int | None = Form(None),
):
    """Upload a plant or field photograph for AI computer vision classification and weed detection."""
    if farm_id is not None:
        farm_service.get_accessible_farm(db, farm_id, current_user, "read", held)

    contents = await file.read()
    if not contents:
        raise ValidationError("Uploaded image file is empty")

    record = plant_identifier.save_and_identify_plant_image(
        db,
        user_id=current_user.id,
        image_bytes=contents,
        filename=file.filename or "plant_capture.jpg",
        mime_type=file.content_type or "image/jpeg",
        farm_id=farm_id,
        zone_id=zone_id,
        hint_crop_id=hint_crop_id,
        ip_address=client_ip(request),
    )
    return PlantIdentificationOut.model_validate(record)


@router.get("/identifications", response_model=PlantIdentificationListOut)
def list_identifications(
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresCropRead,
    farm_id: int | None = None,
    is_weed: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: int = Query(0, ge=0),
):
    """Retrieve plant identification and weed detection history."""
    if farm_id is not None:
        farm_service.get_accessible_farm(db, farm_id, current_user, "read", held)

    items, total = plant_identifier.list_plant_identifications(
        db, farm_id=farm_id, is_weed=is_weed, limit=limit, offset=offset
    )
    return {
        "items": [PlantIdentificationOut.model_validate(x) for x in items],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


@router.post("/identifications/{identification_id}/verify", response_model=PlantIdentificationOut)
def verify_identification(
    identification_id: int,
    payload: PlantIdentificationVerifyIn,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresCropManage,
):
    """Allow an agronomist or farm manager to verify or correct an AI plant identification."""
    record = plant_identifier.verify_plant_identification(
        db,
        identification_id=identification_id,
        user_id=current_user.id,
        status=payload.status,
        verified_crop_id=payload.verified_crop_id,
        notes=payload.notes,
        ip_address=client_ip(request),
    )
    return PlantIdentificationOut.model_validate(record)
