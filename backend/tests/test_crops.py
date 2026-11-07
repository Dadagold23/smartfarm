"""Tests for Module 4 Crop Knowledge Database and Soil Profiles."""

from app.models.soil_profile import SoilTextureType


def _auth_manager(register_user, auth_for, email="crop_manager@agrosmart.farmmail.org"):
    register_user(email)
    return auth_for(email)


def _create_test_farm(client, headers):
    payload = {
        "name": "Valley Agronomy Center",
        "code": "VAC-01",
        "latitude": 36.5,
        "longitude": -119.5,
        "elevation_m": 85.0,
        "area_ha": 50.0,
        "water_source": "borehole",
    }
    resp = client.post("/api/v1/farms", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_seed_and_list_fao_crops(client, register_user, auth_for):
    headers = _auth_manager(register_user, auth_for)

    # Trigger seeding
    seed_resp = client.post("/api/v1/crops/seed-defaults", headers=headers)
    assert seed_resp.status_code == 200, seed_resp.text
    assert seed_resp.json()["seeded_crops"] >= 8

    # List crops
    list_resp = client.get("/api/v1/crops", headers=headers)
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["meta"]["total"] >= 8

    # Filter by category
    cereal_resp = client.get("/api/v1/crops?category=cereal", headers=headers)
    assert cereal_resp.status_code == 200
    cereals = cereal_resp.json()["items"]
    assert any(c["common_name"] == "Maize" for c in cereals)

    # Get single crop by ID with growth stages
    maize_id = next(c["id"] for c in cereals if c["common_name"] == "Maize")
    maize_resp = client.get(f"/api/v1/crops/{maize_id}", headers=headers)
    assert maize_resp.status_code == 200
    maize = maize_resp.json()
    assert maize["common_name"] == "Maize"
    assert maize["scientific_name"] == "Zea mays"
    assert len(maize["growth_stages"]) == 4

    # Verify stage order and Kc values
    stages = maize["growth_stages"]
    initial = next(s for s in stages if s["stage_name"] == "initial")
    mid = next(s for s in stages if s["stage_name"] == "mid_season")
    assert initial["kc_coefficient"] == 0.40
    assert mid["kc_coefficient"] == 1.20


def test_create_and_query_soil_profile(client, register_user, auth_for):
    headers = _auth_manager(register_user, auth_for, email="soil_manager@agrosmart.farmmail.org")
    farm = _create_test_farm(client, headers)

    # Create soil profile with USDA texture preset (loam)
    soil_payload = {
        "farm_id": farm["id"],
        "name": "North Field Loam",
        "texture_type": SoilTextureType.LOAM.value,
        "description": "Rich alluvial loam topsoil",
    }
    resp = client.post("/api/v1/soil-profiles", headers=headers, json=soil_payload)
    assert resp.status_code == 201, resp.text
    profile = resp.json()
    assert profile["name"] == "North Field Loam"
    assert profile["texture_type"] == "loam"
    # Should automatically populate USDA hydraulic parameters
    assert profile["field_capacity"] == 0.27
    assert profile["wilting_point"] == 0.12
    assert profile["saturation"] == 0.46
    assert profile["intake_rate_mm_per_hour"] == 13.0

    # List soil profiles for farm
    list_resp = client.get(f"/api/v1/soil-profiles?farm_id={farm['id']}", headers=headers)
    assert list_resp.status_code == 200
    profiles = list_resp.json()["items"]
    assert len(profiles) == 1
    assert profiles[0]["id"] == profile["id"]
