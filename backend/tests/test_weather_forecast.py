"""Phase 2 Module 6 — provider/forecast write path tests.

The `simulated` provider is exercised end-to-end through the real API;
`open_meteo` parsing is unit-tested against a captured response shape (no
network in tests — its live verification is a manual step documented in
the README); `open_weather_map` must refuse without a key (extension
point contract) instead of faking data.
"""

from datetime import date, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.services.forecast_service import refresh_forecasts
from app.services.weather_providers import available_providers, get_provider
from app.services.weather_providers.base import WeatherProviderError
from app.services.weather_providers.simulator import simulate_day
from app.models.farm import Farm
from app.models.user import User
from app.models.weather import WeatherForecast
from app.services.rbac_service import get_user_permission_codes

FROZEN_ISSUE = datetime(2026, 11, 6, 9, 0, 0)


# ---------------------------------------------------------------------------
# Deterministic simulator provider (pure function)
# ---------------------------------------------------------------------------

def test_simulate_day_is_pure_and_deterministic():
    a = simulate_day(7, date(2026, 11, 6), date(2026, 11, 9))
    b = simulate_day(7, date(2026, 11, 6), date(2026, 11, 9))
    assert a == b
    c = simulate_day(8, date(2026, 11, 6), date(2026, 11, 9))
    assert c.temp_max_c != a.temp_max_c  # farm-scoped seed


def test_simulate_day_within_physical_bounds():
    for farm_id in range(1, 25):
        for lead in range(0, 16):
            d = simulate_day(farm_id, date(2026, 1, 1),
                             date(2026, 1, 1) + timedelta(days=lead))
            assert d.temp_min_c is not None and d.temp_max_c is not None
            assert -40 <= float(d.temp_min_c) <= 85
            assert float(d.temp_min_c) <= float(d.temp_max_c) + 0.01
            assert 0 <= float(d.humidity_pct) <= 100
            assert float(d.wind_speed_m_s) >= 0
            assert float(d.precipitation_mm) >= 0
            assert 0 <= float(d.rain_probability_pct) <= 100
            assert d.confidence == simulate_day(1, date(2026, 1, 1),
                                                date(2026, 1, 1)).confidence


# ---------------------------------------------------------------------------
# Provider registry / contract
# ---------------------------------------------------------------------------

def test_registry_metadata():
    ids = {p["id"]: p for p in available_providers()}
    assert set(ids) == {"simulated", "open_meteo", "open_weather_map"}
    assert ids["simulated"]["is_simulated"] is True
    assert ids["open_meteo"]["is_simulated"] is False
    assert ids["open_meteo"]["configured"] is True          # keyless API
    assert ids["open_weather_map"]["requires_api_key"] is True
    # no key in the test env -> the extension point reports unconfigured
    assert ids["open_weather_map"]["configured"] is (
        bool(get_settings().OPEN_WEATHER_MAP_API_KEY.strip()))


def test_unknown_provider_raises():
    with pytest.raises(WeatherProviderError):
        get_provider("no_such_provider")


def test_key_provider_refuses_without_key():
    prov = get_provider("open_weather_map")
    if get_settings().OPEN_WEATHER_MAP_API_KEY.strip():
        pytest.skip("an API key is configured in this environment")
    with pytest.raises(WeatherProviderError, match="OPEN_WEATHER_MAP_API_KEY"):
        prov.fetch_forecast(Farm(id=1, latitude=1, longitude=1), 7,
                            FROZEN_ISSUE)


def test_open_meteo_parsing(monkeypatch):
    """Offline unit test with a canned live-shaped response (parsing only —
    the actual network call is verified separately, see README)."""
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "daily": {
                    "time": ["2026-11-06", "2026-11-07"],
                    "temperature_2m_min": [18.2, 17.5],
                    "temperature_2m_max": [29.4, 30.1],
                    "relative_humidity_2m_mean": [62.0, 55.5],
                    "wind_speed_10m_max": [3.4, 4.1],
                    "precipitation_sum": [0.0, 2.6],
                    "precipitation_probability_max": [5, 70],
                }
            }

    def fake_get(url, params=None, timeout=None, **kw):
        captured["url"] = url
        captured["params"] = params
        return FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "get", fake_get)
    farm = Farm(id=3, latitude="0.303", longitude="36.08")
    rows = get_provider("open_meteo").fetch_forecast(farm, 2, FROZEN_ISSUE)
    assert captured["url"].endswith("/forecast")
    assert captured["params"]["latitude"] == "0.303"
    assert rows[0].forecast_date == date(2026, 11, 6)
    assert float(rows[1].temp_max_c) == 30.1
    assert float(rows[1].precipitation_mm) == 2.6
    assert rows[0].confidence is None  # provider states none — never invented


def test_open_meteo_requires_coordinates(monkeypatch):
    farm = Farm(id=4, latitude=None, longitude=None)
    with pytest.raises(WeatherProviderError, match="no coordinates"):
        get_provider("open_meteo").fetch_forecast(farm, 3, FROZEN_ISSUE)


# ---------------------------------------------------------------------------
# Refresh write path — service level (deterministic issued_at)
# ---------------------------------------------------------------------------

def test_service_refresh_writes_rows(client, db, device_env):
    # admin owns nothing; use the farm owner's account instead
    from app.models.user import User as U
    owner = db.query(U).filter(U.email == device_env["email"]).one()
    result = refresh_forecasts(
        db, owner, get_user_permission_codes(owner),
        farm_id=device_env["farm_id"], days=7, provider_id="simulated",
        issued_at=FROZEN_ISSUE,
    )
    assert result["created"] == 7 and result["updated"] == 0
    assert result["is_simulated"] is True
    assert result["provider"] == "simulated"
    rows = (db.query(WeatherForecast)
            .filter(WeatherForecast.farm_id == device_env["farm_id"]).all())
    assert len(rows) == 7
    assert [r.lead_time_days for r in rows] == list(range(7))
    assert all(r.provider == "simulated" and r.is_simulated for r in rows)
    # deterministic replay: same issue -> 7 UPDATEs, still 7 rows
    again = refresh_forecasts(
        db, owner, get_user_permission_codes(owner),
        farm_id=device_env["farm_id"], days=7, provider_id="simulated",
        issued_at=FROZEN_ISSUE,
    )
    assert again["created"] == 0 and again["updated"] == 7
    assert db.query(WeatherForecast).count() == 7


# ---------------------------------------------------------------------------
# Refresh endpoint + provenance through the read side
# ---------------------------------------------------------------------------

def test_endpoint_refresh_then_read_back(client, device_env):
    r = client.post(
        "/api/v1/weather/forecast-refresh",
        headers=device_env["headers"],
        json={"farm_id": device_env["farm_id"], "days": 5,
              "provider": "simulated"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 5 and body["is_simulated"] is True
    assert body["provider"] == "simulated"
    assert len(body["items"]) == 5

    g = client.get(
        f"/api/v1/weather/forecasts?farm_id={device_env['farm_id']}",
        headers=device_env["headers"])
    assert g.status_code == 200
    items = g.json()["items"]
    assert len(items) == 5
    assert all(i["provider"] == "simulated" and i["is_simulated"] is True
               for i in items)
    # lead filter works on persisted rows: days=2 -> lead_time_days <= 2,
    # i.e. the issue day itself plus two following days = 3 rows
    g2 = client.get(
        f"/api/v1/weather/forecasts?farm_id={device_env['farm_id']}&days=2",
        headers=device_env["headers"])
    assert len(g2.json()["items"]) == 3


def test_endpoint_default_provider_is_configured_simulator(client, device_env):
    # no provider in the body -> WEATHER_PROVIDER default ("simulator"
    # registry id is 'simulated'), rows flagged simulated either way
    r = client.post("/api/v1/weather/forecast-refresh",
                    headers=device_env["headers"],
                    json={"farm_id": device_env["farm_id"], "days": 3})
    assert r.status_code == 200, r.text
    assert r.json()["is_simulated"] is True


def test_endpoint_unknown_provider_502(client, device_env):
    r = client.post("/api/v1/weather/forecast-refresh",
                    headers=device_env["headers"],
                    json={"farm_id": device_env["farm_id"],
                          "provider": "weather_magic"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "weather_provider_error"


def test_endpoint_cross_owner_farm_404(client, register_user, auth_for,
                                       farm_payload):
    register_user("wxowner@agrosmart.farmmail.org")
    register_user("wxintruder@agrosmart.farmmail.org")
    h1 = auth_for("wxowner@agrosmart.farmmail.org")
    h2 = auth_for("wxintruder@agrosmart.farmmail.org")
    farm = client.post("/api/v1/farms", headers=h1, json=farm_payload).json()
    r = client.post("/api/v1/weather/forecast-refresh", headers=h2,
                    json={"farm_id": farm["id"], "days": 2})
    assert r.status_code == 404  # farm invisible outside ownership scope


def test_endpoint_requires_weather_read(client, db, device_env):
    # every shipped role holds weather.read, so create a role WITHOUT it to
    # prove the permission gate is real
    from app.models.user import Role
    from app.core.security import hash_password
    role = Role(code="wx_none", name="No weather", description="test")
    db.add(role)
    u = User(email="nowx@agrosmart.farmmail.org", full_name="No Wx",
             hashed_password=hash_password("Str0ngPass!phrase"),
             is_active=True)
    u.roles.append(role)
    db.add(u)
    db.commit()
    resp = client.post("/api/v1/weather/forecast-refresh",
                       json={"farm_id": device_env["farm_id"], "days": 2},
                       headers=None)
    assert resp.status_code == 401  # no token at all also blocked
    login = client.post("/api/v1/auth/login",
                        json={"email": "nowx@agrosmart.farmmail.org",
                              "password": "Str0ngPass!phrase"})
    assert login.status_code == 200, login.text
    token = login.json()["tokens"]["access_token"]
    resp2 = client.post("/api/v1/weather/forecast-refresh",
                        json={"farm_id": device_env["farm_id"], "days": 2},
                        headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 403


def test_providers_listing_endpoint(client, device_env):
    r = client.get("/api/v1/weather/forecast-providers",
                   headers=device_env["headers"])
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()["items"]}
    assert ids == {"simulated", "open_meteo", "open_weather_map"}
