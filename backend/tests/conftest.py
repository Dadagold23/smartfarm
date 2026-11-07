"""Shared pytest fixtures.

Environment is pinned BEFORE any `app.*` import so Settings resolves to an
isolated temp SQLite file — tests never touch the dev database.
"""

import os
import tempfile

_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="asiis_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["BCRYPT_ROUNDS"] = "4"  # keep the suite fast; prod uses default 12
os.environ["AUTO_CREATE_TABLES"] = "false"  # tests reset schema explicitly

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base, register_all_models  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.services.rbac_service import sync_rbac  # noqa: E402

PASSWORD = "Str0ngPass!phrase"


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def fresh_schema(db):
    """Full isolation: rebuild schema + RBAC seed before every test."""
    register_all_models()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    sync_rbac(db)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _auth_header(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


@pytest.fixture()
def register_user(client):
    def _register(email: str, full_name: str = "Test User", password: str = PASSWORD):
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": email, "full_name": full_name, "password": password},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _register


@pytest.fixture()
def auth_for(client):
    return lambda email, password=PASSWORD: _auth_header(client, email, password)


@pytest.fixture()
def make_user_with_role(db):
    """Create a user with an arbitrary role set (bypasses self-registration)."""

    def _make(email: str, role_code: str, password: str = PASSWORD) -> User:
        from app.core.security import hash_password

        user = User(
            email=email.lower(),
            full_name=f"{role_code} user",
            hashed_password=hash_password(password),
            is_active=True,
        )
        role = db.query(Role).filter(Role.code == role_code).first()
        assert role is not None
        user.roles.append(role)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture()
def admin(make_user_with_role):
    return make_user_with_role("root@agrosmart.farmmail.org", "admin")


@pytest.fixture()
def farm_payload():
    return {
        "name": "North Ridge Farm",
        "code": "NRF-01",
        "country": "Kenya",
        "region": "Rift Valley",
        "locality": "Nakuru",
        "latitude": "0.303",
        "longitude": "36.08",
        "elevation_m": "1850",
        "area_ha": "40",
        "water_source": "borehole",
    }


# ---------------------------------------------------------------------------
# Phase 2 helpers — IoT devices + telemetry (additive; Phase 1 fixtures
# above are untouched).
# ---------------------------------------------------------------------------

def _make_device(client, headers, farm_id, code, device_type):
    resp = client.post(
        "/api/v1/devices",
        headers=headers,
        json={"farm_id": farm_id, "code": code, "name": code,
              "device_type": device_type},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def device_env(client, register_user, auth_for, farm_payload):
    """farm_manager with one farm, one soil probe and one weather station.

    Returns headers, farm id, device rows and their ONE-TIME plaintext keys.
    """
    register_user("iotmgr@agrosmart.farmmail.org")
    headers = auth_for("iotmgr@agrosmart.farmmail.org")
    farm = client.post("/api/v1/farms", headers=headers, json=farm_payload)
    assert farm.status_code == 201, farm.text
    farm_id = farm.json()["id"]
    soil = _make_device(client, headers, farm_id, "PROBE-1", "soil_probe")
    wx = _make_device(client, headers, farm_id, "WX-1", "weather_station")
    return {
        "headers": headers,
        "email": "iotmgr@agrosmart.farmmail.org",
        "farm_id": farm_id,
        "soil": soil["device"],
        "soil_key": soil["api_key"],
        "wx": wx["device"],
        "wx_key": wx["api_key"],
    }
