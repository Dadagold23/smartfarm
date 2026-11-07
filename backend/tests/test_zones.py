"""Module 2 — irrigation zone CRUD and business rules."""


def _farm(client, headers, payload):
    resp = client.post("/api/v1/farms", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _zone(headers, client, farm_id, **over):
    body = {"name": "Pivot North", "code": "ZN-1", "area_ha": "12", **over}
    return client.post(f"/api/v1/farms/{farm_id}/zones", headers=headers, json=body)


def test_zone_crud_lifecycle(client, register_user, auth_for, farm_payload):
    register_user("zoneowner@agrosmart.farmmail.org")
    headers = auth_for("zoneowner@agrosmart.farmmail.org")
    farm = _farm(client, headers, farm_payload)

    created = _zone(headers, client, farm["id"])
    assert created.status_code == 201, created.text
    zone = created.json()
    assert zone["farm_id"] == farm["id"]
    assert zone["status"] == "active"

    # appears in farm listing (nested brief)
    assert client.get(f"/api/v1/farms/{farm['id']}", headers=headers).json()["zones"]

    byid = client.get(f"/api/v1/zones/{zone['id']}", headers=headers)
    assert byid.status_code == 200

    upd = client.patch(
        f"/api/v1/zones/{zone['id']}",
        headers=headers,
        json={"status": "maintenance", "max_application_mm_per_hour": "8.5"},
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "maintenance"

    assert client.delete(f"/api/v1/zones/{zone['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/zones/{zone['id']}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/farms/{farm['id']}/zones", headers=headers).json() == []


def test_zone_code_unique_per_farm(client, register_user, auth_for, farm_payload):
    register_user("dupz@agrosmart.farmmail.org")
    headers = auth_for("dupz@agrosmart.farmmail.org")
    farm = _farm(client, headers, farm_payload)
    assert _zone(headers, client, farm["id"]).status_code == 201
    assert _zone(headers, client, farm["id"], name="Second").status_code == 409
    # after delete, code can be reused
    zid = client.get(f"/api/v1/farms/{farm['id']}/zones", headers=headers).json()[0]["id"]
    client.delete(f"/api/v1/zones/{zid}", headers=headers)
    assert _zone(headers, client, farm["id"]).status_code == 201


def test_zone_area_cannot_exceed_farm_area(client, register_user, auth_for, farm_payload):
    register_user("big@agrosmart.farmmail.org")
    headers = auth_for("big@agrosmart.farmmail.org")
    farm = _farm(client, headers, farm_payload)  # 40 ha
    over = _zone(headers, client, farm["id"], area_ha="50")
    assert over.status_code == 400
    assert over.json()["error"]["code"] == "business_rule_violation"
    ok1 = _zone(headers, client, farm["id"], area_ha="25", code="ZA")
    ok2 = _zone(headers, client, farm["id"], area_ha="15", code="ZB")
    assert ok1.status_code == ok2.status_code == 201
    too_much = _zone(headers, client, farm["id"], area_ha="5", code="ZC")
    assert too_much.status_code == 400


def test_zones_hidden_across_ownership(client, register_user, auth_for, farm_payload):
    register_user("zq@agrosmart.farmmail.org")
    register_user("zs@agrosmart.farmmail.org")
    ha, hb = auth_for("zq@agrosmart.farmmail.org"), auth_for("zs@agrosmart.farmmail.org")
    farm = _farm(client, ha, farm_payload)
    zone = _zone(ha, client, farm["id"]).json()
    assert client.get(f"/api/v1/zones/{zone['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/farms/{farm['id']}/zones", headers=hb).status_code == 404
    assert _zone(hb, client, farm["id"]).status_code == 404


def test_operator_without_farm_access_cannot_create_zone(
    client, make_user_with_role, auth_for, farm_payload, register_user
):
    register_user("zf@agrosmart.farmmail.org")
    headers = auth_for("zf@agrosmart.farmmail.org")
    farm = _farm(client, headers, farm_payload)
    make_user_with_role("zo@agrosmart.farmmail.org", "operator")
    ho = auth_for("zo@agrosmart.farmmail.org")
    # operator has zone.read but not this farm -> 404 via ownership filter
    assert client.get(f"/api/v1/farms/{farm['id']}/zones", headers=ho).status_code == 404


def test_advisor_reads_zones_everywhere(
    client, register_user, make_user_with_role, auth_for, farm_payload
):
    register_user("za@agrosmart.farmmail.org")
    headers = auth_for("za@agrosmart.farmmail.org")
    farm = _farm(client, headers, farm_payload)
    _zone(headers, client, farm["id"])
    make_user_with_role("zv@agrosmart.farmmail.org", "advisor")
    zones = client.get(
        f"/api/v1/farms/{farm['id']}/zones", headers=auth_for("zv@agrosmart.farmmail.org")
    )
    assert zones.status_code == 200
    assert len(zones.json()) == 1


def test_zone_geometry_validation(client, register_user, auth_for, farm_payload):
    register_user("zg@agrosmart.farmmail.org")
    headers = auth_for("zg@agrosmart.farmmail.org")
    farm = _farm(client, headers, farm_payload)
    bad = _zone(headers, client, farm["id"], geometry="not-json", code="ZB1")
    assert bad.status_code == 422
    good = _zone(
        headers,
        client,
        farm["id"],
        code="ZG",
        geometry='{"type":"Point","coordinates":[36.0,0.3]}',
    )
    assert good.status_code == 201
