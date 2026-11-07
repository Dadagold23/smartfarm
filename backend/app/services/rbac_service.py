"""RBAC service — keeps DB roles/permissions aligned with the code catalog.

Policy (documented in docs/ARCHITECTURE.md):
  * First boot (empty roles table): seed the full catalog.
  * Later boots: only *add* roles/permissions that new code introduces;
    existing role-permission assignments are left exactly as administrators
    set them via the role.manage API (DB is authoritative after first seed;
    code catalog is authoritative for what *exists*).
"""

from sqlalchemy.orm import Session

from app.core.permissions import PERMISSIONS, ROLE_PERMISSIONS
from app.models.user import Permission, Role, User


def sync_rbac(db: Session) -> None:
    existing_perms = {p.code: p for p in db.query(Permission).all()}
    new_perm_codes: set[str] = set()
    for code, desc in PERMISSIONS.items():
        if code not in existing_perms:
            perm = Permission(code=code, description=desc)
            db.add(perm)
            existing_perms[code] = perm
            new_perm_codes.add(code)
    db.flush()

    first_boot = db.query(Role).count() == 0
    for code, spec in ROLE_PERMISSIONS.items():
        role = db.query(Role).filter(Role.code == code).first()
        if role is None:
            role = Role(code=code, name=spec["name"], description=spec["description"])
            db.add(role)
            db.flush()
        if first_boot or not role.permissions:
            # Seed the catalog assignment set (only when unset — admin
            # customisations made afterwards are preserved across restarts).
            role.permissions = [
                existing_perms[p] for p in sorted(spec["permissions"]) if p in existing_perms
            ]
        elif new_perm_codes:
            # Additive upgrade: permission codes introduced by NEW code
            # (e.g. Phase 2 device/sensor/weather) are granted to seeded
            # roles exactly as the catalog declares, without touching any
            # pre-existing assignment an administrator may have tuned.
            held = {p.code for p in role.permissions}
            for add in sorted(spec["permissions"] & new_perm_codes):
                if add not in held:
                    role.permissions.append(existing_perms[add])
    db.commit()


def get_role(db: Session, code: str) -> Role | None:
    return db.query(Role).filter(Role.code == code).first()


def get_user_permission_codes(user: User) -> set[str]:
    codes: set[str] = set()
    for role in user.roles:
        for perm in role.permissions:
            codes.add(perm.code)
    return codes


def assign_role(db: Session, user: User, role: Role) -> None:
    if role not in user.roles:
        user.roles.append(role)
        db.commit()


def user_has_role(user: User, code: str) -> bool:
    return any(r.code == code for r in user.roles)
