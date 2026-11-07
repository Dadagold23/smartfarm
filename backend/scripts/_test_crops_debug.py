import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath("."))

_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="asiis_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["AUTO_CREATE_TABLES"] = "false"

print("Importing app...")
from app.main import app
from fastapi.testclient import TestClient
from app.db.base import Base, register_all_models
from app.db.session import SessionLocal, engine
from app.services.rbac_service import sync_rbac

print("Initializing schema...")
register_all_models()
Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    sync_rbac(db)

print("Starting TestClient...")
with TestClient(app) as client:
    print("Registering user...")
    resp = client.post("/api/v1/auth/register", json={"email": "mgr@agrosmart.farmmail.org", "full_name": "Manager", "password": "Str0ngPass!phrase"})
    print("Register resp:", resp.status_code)
    resp = client.post("/api/v1/auth/login", json={"email": "mgr@agrosmart.farmmail.org", "password": "Str0ngPass!phrase"})
    print("Login resp:", resp.status_code)
    token = resp.json()["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    print("Seeding crops...")
    resp = client.post("/api/v1/crops/seed-defaults", headers=headers)
    print("Seed resp:", resp.status_code, resp.text[:200])

    print("Listing crops...")
    resp = client.get("/api/v1/crops", headers=headers)
    print("List resp:", resp.status_code, resp.json()["meta"])
