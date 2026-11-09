"""Module 10 — AI agricultural advisory tests."""


def test_advisory_generate_for_an_advisor(
    client,
    register_user,
    auth_for,
    make_user_with_role,
    farm_payload,
):
    register_user("mgr@agrosmart.farmmail.org")
    headers = auth_for("mgr@agrosmart.farmmail.org")
    farm = client.post("/api/v1/farms", headers=headers, json=farm_payload)
    assert farm.status_code == 201, farm.text
    farm_id = farm.json()["id"]

    zone = client.post(
        f"/api/v1/farms/{farm_id}/zones",
        headers=headers,
        json={"name": "North Pivot", "code": "Z-01", "area_ha": "12.5"},
    )
    assert zone.status_code == 201, zone.text
    zone_id = zone.json()["id"]

    make_user_with_role("adv@agrosmart.farmmail.org", "advisor")
    adv_headers = auth_for("adv@agrosmart.farmmail.org")

    resp = client.post(
        "/api/v1/advisory/generate",
        headers=adv_headers,
        json={"farm_id": farm_id, "zone_id": zone_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["farm_id"] == farm_id
    assert body["zone_id"] == zone_id
    assert body["risk_level"] in {"low", "moderate", "high"}
    assert body["summary"]
    assert len(body["recommendations"]) >= 1

    alt = client.get(
        f"/api/v1/advisories/generate?farm_id={farm_id}&zone_id={zone_id}",
        headers=adv_headers,
    )
    assert alt.status_code == 200, alt.text
    assert alt.json()["zone_id"] == zone_id


def test_advisory_requires_generate_permission(
    client,
    register_user,
    auth_for,
    farm_payload,
    make_user_with_role,
):
    register_user("mgr2@agrosmart.farmmail.org")
    headers = auth_for("mgr2@agrosmart.farmmail.org")
    farm = client.post("/api/v1/farms", headers=headers, json=farm_payload)
    assert farm.status_code == 201, farm.text
    farm_id = farm.json()["id"]

    zone = client.post(
        f"/api/v1/farms/{farm_id}/zones",
        headers=headers,
        json={"name": "South Pivot", "code": "Z-02", "area_ha": "9.0"},
    )
    assert zone.status_code == 201, zone.text

    make_user_with_role("view2@agrosmart.farmmail.org", "viewer")
    resp = client.post(
        "/api/v1/advisory/generate",
        headers=auth_for("view2@agrosmart.farmmail.org"),
        json={"farm_id": farm_id, "zone_id": zone.json()["id"]},
    )
    assert resp.status_code == 403
