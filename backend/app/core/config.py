"""Application settings.

Loads from environment / .env (pydantic-settings). Defaults are tuned for
local development without external services (SQLite). Production deployment
(architecture Phase 6) overrides DATABASE_URL to PostgreSQL/PostGIS and
SECRET_KEY to a strong random value.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "ASIIS"
    APP_VERSION: str = "0.2.0"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "sqlite:///./agrosmart.db"

    SECRET_KEY: str = "dev-only-insecure-key-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Role granted to self-registered users.
    DEFAULT_SELF_REGISTRATION_ROLE: str = "farm_manager"

    # bcrypt work factor. Keep >= 12 in production; tests lower it via env.
    BCRYPT_ROUNDS: int = 12

    # Create tables on startup when using SQLite dev DB. Production schema
    # changes go through Alembic migrations (backend/alembic).
    AUTO_CREATE_TABLES: bool = True

    # ------------------------------------------------------------------
    # Phase 2 — telemetry / sensor failure detection
    # ------------------------------------------------------------------
    # A device with no accepted reading for this long is reported STALE and
    # a stale_data fault event is raised (spec: "Sensor failure detection").
    TELEMETRY_STALE_MINUTES: int = 120
    # Clock-skew tolerance: device-reported timestamps may not be further in
    # the future than this (ms) or the reading is rejected.
    TELEMETRY_MAX_FUTURE_SKEW_MINUTES: int = 5
    # Flatline detection: N consecutive identical values of one metric
    # (including the new one) => sensor suspected stuck -> flatline fault.
    FLATLINE_CONSECUTIVE_READINGS: int = 3
    # Max readings accepted in one ingestion batch request.
    TELEMETRY_MAX_BATCH: int = 500
    # Hardware operating ranges used for OUT_OF_RANGE fault detection.
    # Keys are "<metric>" (see DEFAULT_OPERATING_RANGES in
    # app/services/telemetry_service.py); values are [min, max] inclusive.
    # Empty (default) = use the code's hardware-spec defaults. Override via
    # env as JSON, e.g. TELEMETRY_OPERATING_RANGES='{"wx.temperature_c": [-20, 50]}'.
    # NOTE: these are sensor *specification* limits (evidence that a device
    # is malfunctioning), never agronomic thresholds.
    TELEMETRY_OPERATING_RANGES: dict[str, list[float]] = {}

    # ------------------------------------------------------------------
    # Phase 2 — weather providers
    # ------------------------------------------------------------------
    # Registry id of the default provider (see app/services/weather_providers):
    # "simulated" (offline, deterministic, every row flagged
    # provider='simulated' + is_simulated — placeholder until Phase 3's FAO
    # data pipeline) or "open_meteo" (real public API, no key required) or
    # "open_weather_map" (real API behind the key extension point below).
    WEATHER_PROVIDER: str = "simulated"
    WEATHER_FORECAST_DAYS: int = 7
    # >>> Real-API-key EXTENSION POINT <<<
    # OpenWeatherMap OneCall is a key-licensed provider. Put the key in the
    # environment (never in code); app/services/weather_providers/
    # open_weather_map.py consumes it. Empty = provider unavailable.
    OPEN_WEATHER_MAP_API_KEY: str = ""
    OPEN_METEO_BASE_URL: str = "https://api.open-meteo.com/v1"
    OPEN_WEATHER_MAP_BASE_URL: str = "https://api.openweathermap.org/data/3.0"
    # HTTP timeout (s) for outbound provider calls.
    WEATHER_PROVIDER_TIMEOUT_S: float = 10.0

    # ------------------------------------------------------------------
    # Phase 2 — MQTT device channel (Module 9)
    # ------------------------------------------------------------------
    # When False (or when the broker is unreachable at startup) the app
    # falls back to the in-process message bus with the identical topic
    # schema — see app/iot/bus.py and README "IoT transport".
    MQTT_ENABLED: bool = False
    MQTT_HOST: str = "127.0.0.1"
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    # TLS for the broker connection (encrypted comms, spec §Security).
    MQTT_USE_TLS: bool = False
    MQTT_CA_CERTS: str = ""
    MQTT_BASE_TOPIC: str = "asiis/v1"

    @field_validator("SECRET_KEY")
    @classmethod
    def _warn_default_secret(cls, v: str) -> str:
        # Non-fatal: tests and local dev run with the default. Deployment
        # checklist (README) requires overriding it.
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
