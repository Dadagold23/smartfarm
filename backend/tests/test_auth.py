"""Module 1 — registration, login, tokens, /me."""

from conftest import PASSWORD


def test_register_returns_tokens_and_default_role(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "Farm@AgroSmart.farmmail.org",
            "full_name": "Grace Farmer",
            "password": PASSWORD,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["email"] == "farm@agrosmart.farmmail.org"  # normalised
    assert [r["code"] for r in body["user"]["roles"]] == ["farm_manager"]
    assert body["tokens"]["token_type"] == "bearer"
    assert body["tokens"]["access_token"] and body["tokens"]["refresh_token"]


def test_register_rejects_weak_password(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.co", "full_name": "Ab", "password": "short"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "request_validation_failed"


def test_register_duplicate_email_conflict(client, register_user):
    register_user("dup@agrosmart.farmmail.org")
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@agrosmart.farmmail.org", "full_name": "Other", "password": PASSWORD},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_login_success_and_me(client, register_user, auth_for):
    register_user("me@agrosmart.farmmail.org")
    headers = auth_for("me@agrosmart.farmmail.org")
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@agrosmart.farmmail.org"


def test_login_wrong_password_no_enumeration(client, register_user):
    register_user("secret@agrosmart.farmmail.org")
    r1 = client.post(
        "/api/v1/auth/login",
        json={"email": "secret@agrosmart.farmmail.org", "password": "WrongPass123!"},
    )
    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@agrosmart.farmmail.org", "password": "WrongPass123!"},
    )
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()  # identical error: no account enumeration


def test_login_deactivated_account_rejected(client, register_user, db):
    register_user("off@agrosmart.farmmail.org")
    from app.models.user import User

    user = db.query(User).filter(User.email == "off@agrosmart.farmmail.org").first()
    user.is_active = False
    db.commit()
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "off@agrosmart.farmmail.org", "password": PASSWORD},
    )
    assert resp.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_rejects_garbage_token(client):
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert resp.status_code == 401


def test_refresh_issues_new_access_token(client, register_user):
    body = register_user("refresh@agrosmart.farmmail.org")
    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": body["tokens"]["refresh_token"]},
    )
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    assert client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"}
    ).status_code == 200


def test_access_token_rejected_at_refresh_endpoint(client, register_user):
    body = register_user("mix@agrosmart.farmmail.org")
    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": body["tokens"]["access_token"]},
    )
    assert resp.status_code == 401


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
