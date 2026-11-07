"""Password hashing and JWT token helpers (Module 1 security core).

bcrypt is used directly (no passlib) for a stable, warning-free dependency
chain. Tokens are standard HS256 JWTs with a `jti` claim so stateless
revocation can be layered on (e.g. Redis deny-list) in a later phase.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

# bcrypt silently ignores input beyond 72 bytes; enforce the limit explicitly.
_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    settings = get_settings()
    data = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(data, bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        data = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
        return bcrypt.checkpw(data, hashed.encode("utf-8"))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Device (machine) credentials — Phase 2, Module 9 device authentication.
# Device API keys are 256-bit random tokens, so the storage scheme is a
# plain SHA-256 digest + constant-time comparison (bcrypt's work factor is
# for low-entropy human passwords and would only slow every telemetry
# message). The plaintext key exists only transiently at registration/
# rotation and is never persisted or logged.
# ---------------------------------------------------------------------------

DEVICE_KEY_PREFIX = "dkey_"


def generate_device_key() -> str:
    return DEVICE_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_device_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_device_key(key: str, stored_hash: str) -> bool:
    if not key or not stored_hash:
        return False
    return hmac.compare_digest(hash_device_key(key), stored_hash)


def create_access_token(
    subject: str,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> tuple[str, datetime]:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(
        payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return token, expires


def create_refresh_token(subject: str) -> tuple[str, datetime]:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 24
    )
    payload = {
        "sub": subject,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
        "jti": uuid.uuid4().hex,
        "type": "refresh",
    }
    token = jwt.encode(
        payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return token, expires


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decode and validate a token. Raises jwt.PyJWTError subclasses."""
    settings = get_settings()
    payload = jwt.decode(
        token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return payload
