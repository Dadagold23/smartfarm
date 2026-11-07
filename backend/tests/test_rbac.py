"""Module 1 — roles, permissions, admin user management."""

from conftest import PASSWORD


def test_rbac_catalog_seeded(client, admin, auth_for):
    headers = auth_for(admin.email)
    roles = client.get("/api/v1/roles", headers=headers)
    assert roles.status_code == 200
    codes = {r["code"] for r in roles.json()}
    assert {"admin", "farm_manager", "operator", "advisor", "viewer"} <= codes
    perms = client.get("/api/v1/permissions", headers=headers)
    assert perms.status_code == 200
    assert any(p["code"] == "farm.create" for p in perms.json())


def test_non_admin_cannot_list_roles(client, register_user, auth_for):
    register_user("mgr@agrosmart.farmmail.org")
    resp = client.get("/api/v1/roles", headers=auth_for("mgr@agrosmart.farmmail.org"))
    assert resp.status_code == 403
    assert "role.read" in resp.json()["detail"]


def test_admin_creates_user_with_roles(client, admin, auth_for):
    resp = client.post(
        "/api/v1/users",
        headers=auth_for(admin.email),
        json={
            "email": "op@agrosmart.farmmail.org",
            "full_name": "Opi Operator",
            "password": PASSWORD,
            "role_codes": ["operator", "viewer"],
        },
    )
    assert resp.status_code == 201, resp.text
    assert sorted(resp.json()["roles"]) == ["operator", "viewer"]


def test_admin_rejects_unknown_role(client, admin, auth_for):
    resp = client.post(
        "/api/v1/users",
        headers=auth_for(admin.email),
        json={
            "email": "bad@agrosmart.farmmail.org",
            "full_name": "Bad Role",
            "password": PASSWORD,
            "role_codes": ["wizard"],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_farm_manager_cannot_create_users(client, register_user, auth_for):
    register_user("mgr2@agrosmart.farmmail.org")
    resp = client.post(
        "/api/v1/users",
        headers=auth_for("mgr2@agrosmart.farmmail.org"),
        json={
            "email": "sneaky@agrosmart.farmmail.org",
            "full_name": "Sneaky",
            "password": PASSWORD,
            "role_codes": ["admin"],
        },
    )
    assert resp.status_code == 403


def test_role_assignment_change(client, admin, make_user_with_role, auth_for):
    target = make_user_with_role("flip@agrosmart.farmmail.org", "viewer")
    resp = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=auth_for(admin.email),
        json={"role_codes": ["operator"]},
    )
    assert resp.status_code == 200
    assert resp.json()["roles"] == ["operator"]


def test_admin_cannot_change_own_roles(client, admin, auth_for):
    resp = client.put(
        f"/api/v1/users/{admin.id}/roles",
        headers=auth_for(admin.email),
        json={"role_codes": ["viewer"]},
    )
    assert resp.status_code == 400


def test_admin_cannot_lock_out_role_management(client, admin, auth_for):
    resp = client.patch(
        "/api/v1/roles/admin/permissions",
        headers=auth_for(admin.email),
        json={"permissions": ["user.read"]},
    )
    assert resp.status_code == 400  # admin must keep role.manage


def test_admin_edits_role_permissions_effective_immediately(
    client, admin, make_user_with_role, auth_for
):
    viewer = make_user_with_role("v1@agrosmart.farmmail.org", "viewer")
    headers = auth_for(viewer.email)
    # viewer has no farm.create -> blocked
    blocked = client.post("/api/v1/farms", headers=headers, json={"name": "X Y", "code": "Z1"})
    assert blocked.status_code == 403
    # grant farm.create to viewer via role management
    admin_headers = auth_for(admin.email)
    roles_before = client.get("/api/v1/roles", headers=admin_headers).json()
    viewer_perms = next(r["permissions"] for r in roles_before if r["code"] == "viewer")
    resp = client.patch(
        "/api/v1/roles/viewer/permissions",
        headers=admin_headers,
        json={"permissions": sorted(set(viewer_perms) | {"farm.create"})},
    )
    assert resp.status_code == 200
    # new token reflects updated permission
    ok = client.post(
        "/api/v1/farms",
        headers=auth_for(viewer.email),
        json={"name": "Now Farm", "code": "NF1"},
    )
    assert ok.status_code == 201, ok.text


def test_user_list_scoping(client, admin, auth_for, register_user):
    register_user("plain@agrosmart.farmmail.org")
    resp = client.get("/api/v1/users", headers=auth_for(admin.email))
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()["items"]}
    assert "plain@agrosmart.farmmail.org" in emails
