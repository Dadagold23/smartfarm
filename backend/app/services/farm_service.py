"""Module 2 business logic: farms and irrigation zones.

Authorization model (see docs/ARCHITECTURE.md §RBAC):
  * farm.{action}.own  → only farms where farm.owner_id == user.id
  * farm.{action}.all  → any farm (admin / advisor as applicable)
Zones inherit the farm-level check: zone.* permissions gate the action,
and the parent farm must be accessible at the corresponding level.
"""

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import satisfies
from app.models.farm import Farm, IrrigationZone
from app.models.user import User
from app.services import audit_service

FARM_ACTIONS = ("read", "update", "delete")


def _farm_access_required(action: str, farm: Farm, user: User, held: set[str]) -> bool:
    if satisfies(f"farm.{action}.all", held):
        return True
    if satisfies(f"farm.{action}.own", held) and farm.owner_id == user.id:
        return True
    return False


def get_accessible_farm(
    db: Session, farm_id: int, user: User, action: str, held: set[str]
) -> Farm:
    farm = db.query(Farm).filter(Farm.id == farm_id, Farm.is_deleted.is_(False)).first()
    if farm is None or not _farm_access_required(action, farm, user, held):
        # 404 (not 403) for inaccessible existing farms: no resource
        # enumeration across ownership boundaries.
        raise NotFoundError(f"farm {farm_id} not found")
    return farm


def list_farms(
    db: Session, user: User, held: set[str], *, limit: int, offset: int,
    status: str | None = None, search: str | None = None,
) -> tuple[list[Farm], int]:
    q = db.query(Farm).filter(Farm.is_deleted.is_(False))
    if not satisfies("farm.read.all", held):
        if not satisfies("farm.read.own", held):
            raise NotFoundError("no farms visible with current permissions")
        q = q.filter(Farm.owner_id == user.id)
    if status:
        from app.core.exceptions import ValidationError as _V

        from app.models.farm import FarmStatus as _FS

        try:
            status_enum = _FS(status)
        except ValueError as exc:
            raise _V(f"invalid farm status '{status}'") from exc
        q = q.filter(Farm.status == status_enum)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            Farm.name.ilike(like) | Farm.code.ilike(like) | Farm.locality.ilike(like)
        )
    total = q.count()
    items = q.order_by(Farm.id).limit(limit).offset(offset).all()
    return items, total


def create_farm(
    db: Session, payload, user: User, held: set[str], ip_address: str = ""
) -> Farm:
    if not satisfies("farm.create", held):
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("missing permission farm.create")
    owner = user
    # Admins may create farms on behalf of another user.
    if getattr(payload, "owner_id", None) is not None:
        if not satisfies("farm.read.all", held):
            from app.core.exceptions import PermissionDeniedError

            raise PermissionDeniedError("only users with farm.read.all may set owner_id")
        from app.models.user import User as U
        target = db.get(U, payload.owner_id)
        if target is None:
            raise NotFoundError(f"user {payload.owner_id} does not exist")
        owner = target
    code = payload.code.strip()
    clash = (
        db.query(Farm)
        .filter(Farm.owner_id == owner.id, Farm.code == code, Farm.is_deleted.is_(False))
        .first()
    )
    if clash:
        raise ConflictError(f"you already have a farm with code '{code}'")
    farm = Farm(
        owner_id=owner.id,
        name=payload.name.strip(),
        code=code,
        description=payload.description or "",
        country=payload.country or "",
        region=payload.region or "",
        locality=payload.locality or "",
        latitude=payload.latitude,
        longitude=payload.longitude,
        elevation_m=payload.elevation_m,
        geometry=payload.geometry,
        area_ha=payload.area_ha,
        water_source=payload.water_source,
        status=payload.status,
    )
    db.add(farm)
    db.flush()
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="farm.create",
        resource_type="farm", resource_id=farm.id,
        details={"code": farm.code, "owner_id": farm.owner_id}, ip_address=ip_address,
    )
    db.commit()
    db.refresh(farm)
    return farm


def update_farm(db: Session, farm_id: int, payload, user: User, held: set[str], ip_address: str = "") -> Farm:
    farm = get_accessible_farm(db, farm_id, user, "update", held)
    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"] != farm.code:
        clash = (
            db.query(Farm)
            .filter(Farm.owner_id == farm.owner_id, Farm.code == data["code"],
                    Farm.id != farm.id, Farm.is_deleted.is_(False))
            .first()
        )
        if clash:
            raise ConflictError(f"a farm with code '{data['code']}' already exists")
    for field, value in data.items():
        setattr(farm, field, value)
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="farm.update",
        resource_type="farm", resource_id=farm.id,
        details={"fields": sorted(data.keys())}, ip_address=ip_address,
    )
    db.commit()
    db.refresh(farm)
    return farm


def delete_farm(db: Session, farm_id: int, user: User, held: set[str], ip_address: str = "") -> None:
    farm = get_accessible_farm(db, farm_id, user, "delete", held)
    active_zones = (
        db.query(IrrigationZone)
        .filter(IrrigationZone.farm_id == farm.id, IrrigationZone.is_deleted.is_(False))
        .count()
    )
    if active_zones:
        raise BusinessRuleError(
            "farm still has irrigation zones; delete or move them first"
        )
    farm.is_deleted = True
    # Tombstone the unique code so owners can reuse it for a new farm.
    farm.code = f"{farm.code}~del{farm.id}"[:32]
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="farm.delete",
        resource_type="farm", resource_id=farm.id, ip_address=ip_address,
    )
    db.commit()


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def _farm_needs_zone_access(action: str) -> str:
    return "read" if action == "read" else "update"


def list_zones(db: Session, farm_id: int, user: User, held: set[str]) -> list[IrrigationZone]:
    farm = get_accessible_farm(db, farm_id, user, "read", held)
    if not satisfies("zone.read", held):
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("missing permission zone.read")
    return [z for z in farm.zones if not z.is_deleted]


def create_zone(db: Session, farm_id: int, payload, user: User, held: set[str], ip_address: str = "") -> IrrigationZone:
    farm = get_accessible_farm(db, farm_id, user, _farm_needs_zone_access("create"), held)
    if not satisfies("zone.create", held):
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("missing permission zone.create")
    # Business rule: zones cannot exceed the farm's declared area.
    if payload.area_ha and farm.area_ha:
        used = sum(
            (z.area_ha or 0) for z in farm.zones if not z.is_deleted
        )
        if used + payload.area_ha > farm.area_ha:
            raise BusinessRuleError(
                f"zone area exceeds remaining farm area ({farm.area_ha} ha total)"
            )
    code = payload.code.strip()
    clash = (
        db.query(IrrigationZone)
        .filter(IrrigationZone.farm_id == farm.id, IrrigationZone.code == code,
               IrrigationZone.is_deleted.is_(False))
        .first()
    )
    if clash:
        raise ConflictError(f"farm already has a zone with code '{code}'")
    zone = IrrigationZone(
        farm_id=farm.id,
        name=payload.name.strip(),
        code=code,
        area_ha=payload.area_ha,
        sequence_number=payload.sequence_number,
        status=payload.status,
        geometry=payload.geometry,
        max_application_mm_per_hour=payload.max_application_mm_per_hour,
    )
    db.add(zone)
    db.flush()
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="zone.create",
        resource_type="irrigation_zone", resource_id=zone.id,
        details={"farm_id": farm.id, "code": zone.code}, ip_address=ip_address,
    )
    db.commit()
    db.refresh(zone)
    return zone


def get_zone(db: Session, zone_id: int, user: User, held: set[str], farm_action: str) -> IrrigationZone:
    zone = (
        db.query(IrrigationZone)
        .filter(IrrigationZone.id == zone_id, IrrigationZone.is_deleted.is_(False))
        .first()
    )
    if zone is None:
        raise NotFoundError(f"zone {zone_id} not found")
    get_accessible_farm(db, zone.farm_id, user, farm_action, held)
    return zone


def update_zone(db: Session, zone_id: int, payload, user: User, held: set[str], ip_address: str = "") -> IrrigationZone:
    if not satisfies("zone.update", held):
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("missing permission zone.update")
    zone = get_zone(db, zone_id, user, held, "update")
    farm = db.get(Farm, zone.farm_id)
    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"] != zone.code:
        clash = (
            db.query(IrrigationZone)
            .filter(IrrigationZone.farm_id == zone.farm_id,
                    IrrigationZone.code == data["code"],
                    IrrigationZone.id != zone.id,
                    IrrigationZone.is_deleted.is_(False))
            .first()
        )
        if clash:
            raise ConflictError(f"farm already has a zone with code '{data['code']}'")
    if "area_ha" in data and data["area_ha"] and farm is not None and farm.area_ha:
        used = sum(
            (z.area_ha or 0) for z in farm.zones
            if not z.is_deleted and z.id != zone.id
        )
        if used + data["area_ha"] > farm.area_ha:
            raise BusinessRuleError("zone area exceeds remaining farm area")
    for field, value in data.items():
        setattr(zone, field, value)
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="zone.update",
        resource_type="irrigation_zone", resource_id=zone.id,
        details={"fields": sorted(data.keys())}, ip_address=ip_address,
    )
    db.commit()
    db.refresh(zone)
    return zone


def delete_zone(db: Session, zone_id: int, user: User, held: set[str], ip_address: str = "") -> None:
    if not satisfies("zone.delete", held):
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("missing permission zone.delete")
    zone = get_zone(db, zone_id, user, held, "update")
    zone.is_deleted = True
    # Tombstone the unique code so the farm can reuse it for a new zone.
    zone.code = f"{zone.code}~del{zone.id}"[:32]
    audit_service.log(
        db, user_id=user.id, actor_label=user.email, action="zone.delete",
        resource_type="irrigation_zone", resource_id=zone.id,
        details={"farm_id": zone.farm_id}, ip_address=ip_address,
    )
    db.commit()
