"""Shared API dependencies: DB session, current user, permission checks,
Phase 2 device (machine) authentication for telemetry ingestion."""

from dataclasses import dataclass
from typing import Annotated, Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
)
from sqlalchemy.orm import Session

from app.core.permissions import satisfies
from app.core.security import decode_token
from app.db.session import get_db
from app.models.iot import Device
from app.models.user import User
from app.services.rbac_service import get_user_permission_codes

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def _user_from_bearer(db: Session, token: str) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token, expected_type="access")
    except pyjwt.PyJWTError:
        raise credentials_exc from None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise credentials_exc from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exc
    return user


def get_current_user(
    db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    return _user_from_bearer(db, token)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_permission_codes(current_user: CurrentUser) -> set[str]:
    return get_user_permission_codes(current_user)


HeldPermissions = Annotated[set[str], Depends(get_permission_codes)]


def require_permissions(*required: str):
    """Dependency factory: user must satisfy every required permission code
    (own/all expansion handled by `satisfies`)."""

    def dependency(held: HeldPermissions) -> set[str]:
        missing = [code for code in required if not satisfies(code, held)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permissions: {', '.join(missing)}",
            )
        return held

    return dependency


def client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


# ---------------------------------------------------------------------------
# Phase 2 — device (machine) authentication for telemetry ingestion.
# Device keys are independent of user JWTs (docs/ARCHITECTURE.md §8): the
# digest of the presented key is looked up and constant-time verified; a
# revoked device is rejected immediately, no key caching.
# ---------------------------------------------------------------------------

device_key_header = APIKeyHeader(name="X-Device-Key", auto_error=False)


def authenticate_device_key(db: Session, api_key: str | None) -> Device:
    """Resolve an active device from a presented key; 401 otherwise.

    The lookup/verification rule itself lives in
    `device_service.authenticate_device_key` — the SAME function the MQTT
    channel handler calls — so HTTP and MQTT can never drift apart.
    """
    from app.core.exceptions import AuthenticationError
    from app.services import device_service

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid device key",
        headers={"WWW-Authenticate": "X-Device-Key"},
    )
    try:
        return device_service.authenticate_device_key(db, api_key)
    except AuthenticationError as exc:
        if "revoked" in exc.message:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="device credentials revoked",
                headers={"WWW-Authenticate": "X-Device-Key"},
            ) from None
        raise unauthorized from None


@dataclass
class IngestIdentity:
    """Who is pushing telemetry: a device (machine cred) or a JWT user
    holding `telemetry.ingest` on behalf of a device (manual backfill)."""

    device: Device | None
    user: User | None
    held: set[str]
    actor_label: str


def resolve_ingest_identity(
    db: DbSession,
    api_key: Annotated[Optional[str], Depends(device_key_header)],
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)
    ],
) -> IngestIdentity:
    if api_key:
        device = authenticate_device_key(db, api_key)
        return IngestIdentity(
            device=device, user=None, held=set(),
            actor_label=f"device:{device.code}",
        )
    if credentials is not None:
        user = _user_from_bearer(db, credentials.credentials)
        held = get_user_permission_codes(user)
        if not satisfies("telemetry.ingest", held):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="missing permissions: telemetry.ingest",
            )
        return IngestIdentity(
            device=None, user=user, held=held, actor_label=user.email
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="provide X-Device-Key or a Bearer token",
        headers={"WWW-Authenticate": "X-Device-Key, Bearer"},
    )
