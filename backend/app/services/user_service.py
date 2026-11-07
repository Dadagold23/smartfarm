"""Module 1 business logic: registration, authentication, user management."""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.security import hash_password, verify_password
from app.models.user import Role, User
from app.services import audit_service, rbac_service


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == _normalize_email(email)).first()


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"user {user_id} does not exist")
    return user


def register_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    default_role_code: str,
    ip_address: str = "",
) -> User:
    email = _normalize_email(email)
    if get_user_by_email(db, email):
        raise ConflictError("an account with this email already exists")
    role = rbac_service.get_role(db, default_role_code)
    if role is None:
        raise ValidationError(
            f"default role '{default_role_code}' is not provisioned; run RBAC sync"
        )
    user = User(
        email=email,
        full_name=full_name.strip(),
        hashed_password=hash_password(password),
        is_active=True,
    )
    user.roles.append(role)
    db.add(user)
    db.flush()
    audit_service.log(
        db,
        user_id=user.id,
        actor_label=user.email,
        action="auth.register",
        resource_type="user",
        resource_id=user.id,
        details={"role": role.code},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str, ip_address: str = "") -> User:
    user = get_user_by_email(db, email)
    # Same error for unknown email and bad password: no account enumeration.
    if user is None or not verify_password(password, user.hashed_password):
        raise AuthenticationError("incorrect email or password")
    if not user.is_active:
        raise AuthenticationError("account is deactivated")
    user.last_login_at = datetime.now(timezone.utc)
    audit_service.log(
        db,
        user_id=user.id,
        actor_label=user.email,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session, *, limit: int = 50, offset: int = 0) -> tuple[list[User], int]:
    q = db.query(User)
    total = q.count()
    return q.order_by(User.id).limit(limit).offset(offset).all(), total


def create_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    role_codes: list[str],
    actor: User,
    ip_address: str = "",
) -> User:
    email = _normalize_email(email)
    if get_user_by_email(db, email):
        raise ConflictError("an account with this email already exists")
    user = User(
        email=email,
        full_name=full_name.strip(),
        hashed_password=hash_password(password),
        is_active=True,
    )
    for code in role_codes:
        role = rbac_service.get_role(db, code)
        if role is None:
            raise ValidationError(f"unknown role '{code}'")
        user.roles.append(role)
    db.add(user)
    db.flush()
    audit_service.log(
        db,
        user_id=actor.id,
        actor_label=actor.email,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email, "roles": role_codes},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user_id: int,
    *,
    full_name: str | None = None,
    email: str | None = None,
    is_active: bool | None = None,
    actor: User,
    ip_address: str = "",
) -> User:
    user = get_user(db, user_id)
    changed: dict = {}
    if full_name is not None:
        user.full_name = full_name.strip()
        changed["full_name"] = full_name
    if email is not None:
        new_email = _normalize_email(email)
        clash = get_user_by_email(db, new_email)
        if clash and clash.id != user.id:
            raise ConflictError("another account already uses this email")
        user.email = new_email
        changed["email"] = new_email
    if is_active is not None:
        user.is_active = is_active
        changed["is_active"] = is_active
    audit_service.log(
        db,
        user_id=actor.id,
        actor_label=actor.email,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        details=changed,
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(user)
    return user


def set_user_roles(
    db: Session, user_id: int, role_codes: list[str], actor: User, ip_address: str = ""
) -> User:
    user = get_user(db, user_id)
    roles: list[Role] = []
    for code in role_codes:
        role = rbac_service.get_role(db, code)
        if role is None:
            raise ValidationError(f"unknown role '{code}'")
        roles.append(role)
    user.roles = roles
    audit_service.log(
        db,
        user_id=actor.id,
        actor_label=actor.email,
        action="user.set_roles",
        resource_type="user",
        resource_id=user.id,
        details={"roles": role_codes},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(user)
    return user


def count_admins(db: Session) -> int:
    return (
        db.query(func.count(User.id))
        .join(User.roles)
        .filter(Role.code == "admin", User.is_active.is_(True))
        .scalar()
        or 0
    )
