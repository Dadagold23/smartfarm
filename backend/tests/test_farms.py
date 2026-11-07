"""Module 2 — farm CRUD, ownership isolation, role scoping."""


def _create_farm(client, headers, payload, **overrides):
    body = {**payload, **overrides}
    return client.post("/api/v1/farms", headers=headers, json=body)


def test_create_and_read_farm(client, register_user, auth_for, farm_payload):
    register_user("owner@agrosmart.farmmail.org")
    headers = auth_for("owner@agrosmart.farmmail.org")
    created = _create_farm(client, headers, farm_payload)
    assert created.status_code == 201, created.text
    farm = created.json()
    assert farm["code"] == "NRF-01"
    assert farm["water_source"] == "borehole"
    assert farm["zones"] == []

    fetched = client.get(f"/api/v1/farms/{farm['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "North Ridge Farm"

    listed = client.get("/api/v1/farms", headers=headers)
    assert listed.json()["meta"]["total"] == 1


def test_duplicate_farm_code_per_owner_conflict(
    client, register_user, auth_for, farm_payload
):
    register_user("dupowner@agrosmart.farmmail.org")
    headers = auth_for("dupowner@agrosmart.farmmail.org")
    assert _create_farm(client, headers, farm_payload).status_code == 201
    again = _create_farm(client, headers, farm_payload, name="Same Code Farm")
    assert again.status_code == 409


def test_other_users_farm_invisible(client, register_user, auth_for, farm_payload):
    register_user("a@agrosmart.farmmail.org")
    register_user("b@agrosmart.farmmail.org")
    ha, hb = auth_for("a@agrosmart.farmmail.org"), auth_for("b@agrosmart.farmmail.org")
    farm = _create_farm(client, ha, farm_payload).json()

    # 404, not 403: no enumeration of other people's resources.
    assert client.get(f"/api/v1/farms/{farm['id']}", headers=hb).status_code == 404
    assert client.get("/api/v1/farms", headers=hb).json()["meta"]["total"] == 0
    assert (
        client.patch(f"/api/v1/farms/{farm['id']}", headers=hb, json={"name": "Hijack"})
    ).status_code == 404
    assert client.delete(f"/api/v1/farms/{farm['id']}", headers=hb).status_code == 404


def test_update_farm_partial(client, register_user, auth_for, farm_payload):
    register_user("upd@agrosmart.farmmail.org")
    headers = auth_for("upd@agrosmart.farmmail.org")
    farm = _create_farm(client, headers, farm_payload).json()
    resp = client.patch(
        f"/api/v1/farms/{farm['id']}",
        headers=headers,
        json={"status": "inactive", "area_ha": "45.5"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"
    assert float(resp.json()["area_ha"]) == 45.5


def test_delete_farm_soft_and_blocks_when_zones_exist(
    client, register_user, auth_for, farm_payload
):
    register_user("del@agrosmart.farmmail.org")
    headers = auth_for("del@agrosmart.farmmail.org")
    farm = _create_farm(client, headers, farm_payload).json()

    client.post(
        f"/api/v1/farms/{farm['id']}/zones",
        headers=headers,
        json={"name": "Pivot A", "code": "Z1", "area_ha": "10"},
    )
    blocked = client.delete(f"/api/v1/farms/{farm['id']}", headers=headers)
    assert blocked.status_code == 400

    zone = client.get(f"/api/v1/farms/{farm['id']}/zones", headers=headers).json()[0]
    client.delete(f"/api/v1/zones/{zone['id']}", headers=headers)
    assert client.delete(f"/api/v1/farms/{farm['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/farms/{farm['id']}", headers=headers).status_code == 404


def test_advisor_reads_any_farm_but_cannot_update(
    client, register_user, make_user_with_role, auth_for, farm_payload, db
):
    register_user("mgrx@agrosmart.farmmail.org")
    hm = auth_for("mgrx@agrosmart.farmmail.org")
    farm = _create_farm(client, hm, farm_payload).json()

    make_user_with_role("adv@agrosmart.farmmail.org", "advisor")
    ha = auth_for("adv@agrosmart.farmmail.org")
    assert client.get(f"/api/v1/farms/{farm['id']}", headers=ha).status_code == 200
    assert (
        client.patch(f"/api/v1/farms/{farm['id']}", headers=ha, json={"name": "Nope"})
    ).status_code == 404  # hidden behind ownership filter


def test_admin_creates_farm_for_other_user_and_edits_it(
    client, admin, make_user_with_role, auth_for, farm_payload
):
    mgr = make_user_with_role("owned@agrosmart.farmmail.org", "farm_manager")
    ha = auth_for(admin.email)
    created = _create_farm(client, ha, farm_payload, owner_id=mgr.id)
    assert created.status_code == 201
    farm = created.json()
    assert farm["owner_id"] == mgr.id

    # The owning manager sees it; admin (farm.update.all) can edit it.
    hm = auth_for(mgr.email)
    assert client.get(f"/api/v1/farms/{farm['id']}", headers=hm).status_code == 200
    assert client.patch(
        f"/api/v1/farms/{farm['id']}", headers=ha, json={"locality": "Eldoret"}
    ).json()["locality"] == "Eldoret"


def test_operator_sees_only_own_empty_scope(
    client, make_user_with_role, auth_for, farm_payload, register_user, admin
):
    make_user_with_role("oper@agrosmart.farmmail.org", "operator")
    ho = auth_for("oper@agrosmart.farmmail.org")
    assert client.get("/api/v1/farms", headers=ho).json()["meta"]["total"] == 0
    # operator cannot create farms
    assert _create_farm(client, ho, farm_payload).status_code == 403


def test_viewer_cannot_create(client, make_user_with_role, auth_for, farm_payload):
    make_user_with_role("view@agrosmart.farmmail.org", "viewer")
    assert _create_farm(
        client, auth_for("view@agrosmart.farmmail.org"), farm_payload
    ).status_code == 403


def test_farm_validation_bad_coords(client, register_user, auth_for, farm_payload):
    register_user("geo@agrosmart.farmmail.org")
    resp = _create_farm(
        client, auth_for("geo@agrosmart.farmmail.org"), farm_payload, latitude="95"
    )
    assert resp.status_code == 422


def test_pagination_and_search(client, register_user, auth_for, farm_payload):
    register_user("pg@agrosmart.farmmail.org")
    headers = auth_for("pg@agrosmart.farmmail.org")
    for i in range(3):
        _create_farm(client, headers, farm_payload, code=f"F{i}", name=f"Farm {i}")
    page = client.get("/api/v1/farms?limit=2&offset=1", headers=headers)
    assert page.status_code == 200
    assert len(page.json()["items"]) == 2
    assert page.json()["meta"]["total"] == 3
    found = client.get("/api/v1/farms?search=Farm 2", headers=headers).json()
    assert found["meta"]["total"] == 1
