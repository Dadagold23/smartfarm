"""Module 7 — Irrigation Scheduling and FAO-56 Water Balance endpoints."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, client_ip, require_permissions
from app.schemas.schedule import (
    ScheduleApproveIn,
    ScheduleCalculateIn,
    ScheduleListOut,
    ScheduleOut,
    ScheduleRejectIn,
)
from app.services import farm_service, schedule_service

router = APIRouter()

RequiresScheduleRead = Annotated[set[str], Depends(require_permissions("schedule.read"))]
RequiresScheduleManage = Annotated[set[str], Depends(require_permissions("schedule.manage"))]


@router.get("", response_model=ScheduleListOut)
def list_schedules(
    farm_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresScheduleRead,
    zone_id: int | None = None,
    target_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """List calculated irrigation schedules and water balance runs."""
    farm_service.get_accessible_farm(db, farm_id, current_user, "read", held)
    items = schedule_service.list_schedules_for_farm(
        db, farm_id=farm_id, zone_id=zone_id, target_date=target_date, limit=limit
    )
    return {"items": [ScheduleOut.model_validate(s) for s in items]}


@router.post("/calculate", response_model=ScheduleOut, status_code=201)
def calculate_schedule(
    payload: ScheduleCalculateIn,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresScheduleManage,
):
    """Run full FAO-56 Penman-Monteith & root-zone water balance to generate an irrigation recommendation."""
    farm_service.get_accessible_farm(db, payload.farm_id, current_user, "update", held)
    schedule = schedule_service.calculate_zone_irrigation_schedule(
        db,
        farm_id=payload.farm_id,
        zone_id=payload.zone_id,
        target_date=payload.target_date,
        actor_id=current_user.id,
        ip_address=client_ip(request),
    )
    return ScheduleOut.model_validate(schedule)


@router.get("/{schedule_id}", response_model=ScheduleOut)
def get_schedule(
    schedule_id: int,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresScheduleRead,
):
    """Retrieve detailed schedule record including equation inputs and intermediate terms."""
    item = schedule_service.get_schedule_by_id(db, schedule_id)
    farm_service.get_accessible_farm(db, item.farm_id, current_user, "read", held)
    return ScheduleOut.model_validate(item)


@router.post("/{schedule_id}/approve", response_model=ScheduleOut)
def approve_schedule(
    schedule_id: int,
    payload: ScheduleApproveIn,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresScheduleManage,
):
    """Authorise a recommended irrigation schedule."""
    item = schedule_service.get_schedule_by_id(db, schedule_id)
    farm_service.get_accessible_farm(db, item.farm_id, current_user, "update", held)
    updated = schedule_service.approve_irrigation_schedule(
        db,
        schedule_id=item.id,
        user_id=current_user.id,
        notes=payload.notes,
        ip_address=client_ip(request),
    )
    return ScheduleOut.model_validate(updated)


@router.post("/{schedule_id}/reject", response_model=ScheduleOut)
def reject_schedule(
    schedule_id: int,
    payload: ScheduleRejectIn,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    held: RequiresScheduleManage,
):
    """Reject or cancel a schedule."""
    item = schedule_service.get_schedule_by_id(db, schedule_id)
    farm_service.get_accessible_farm(db, item.farm_id, current_user, "update", held)
    updated = schedule_service.reject_or_cancel_schedule(
        db,
        schedule_id=item.id,
        user_id=current_user.id,
        reason=payload.reason,
        ip_address=client_ip(request),
    )
    return ScheduleOut.model_validate(updated)
