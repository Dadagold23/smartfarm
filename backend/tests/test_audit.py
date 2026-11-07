"""Audit trail: state changes are recorded and access is permission-scoped."""


def test_audit_records_register_login_and_farm_actions(
    client, register_user, auth_for, farm_payload, admin
):
    register_user("aud@agrosmart.farmmail.org")
    headers = auth_for("aud@agrosmart.farmmail.org")
    client.post("/api/v1/farms", headers=headers, json=farm_payload)

    logs = client.get("/api/v1/audit-logs", headers=headers).json()
    actions = {item["action"] for item in logs["items"]}
    assert {"auth.register", "auth.login", "farm.create"} <= actions
    # scoped to own activity only
    assert all(item["user_id"] == logs["items"][0]["user_id"] for item in logs["items"])


def test_admin_sees_all_audit_logs(client, register_user, auth_for, admin, farm_payload):
    register_user("other@agrosmart.farmmail.org")
    register_user("second@agrosoft.farmmail.org")
    all_logs = client.get("/api/v1/audit-logs", headers=auth_for(admin.email)).json()
    actor_ids = {item["user_id"] for item in all_logs["items"]}
    assert len(actor_ids) >= 2  # multiple users' activity visible to admin


def test_viewer_without_audit_permission_gets_403(
    client, make_user_with_role, auth_for
):
    make_user_with_role("noaud@agrosmart.farmmail.org", "viewer")
    resp = client.get("/api/v1/audit-logs", headers=auth_for("noaud@agrosmart.farmmail.org"))
    assert resp.status_code == 403
