"""ASIIS FastAPI application entrypoint.

Run (from backend/):
    uvicorn app.main:app --reload --port 8000
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.base import Base, register_all_models
from app.db.session import SessionLocal, engine
from app.iot.bus import get_bus
from app.iot.handler import make_bus_subscriber
from app.iot.mqtt_client import start_if_enabled
from app.iot.topics import subscription_wildcard
from app.services.crop_service import seed_standard_crop_database
from app.services.rbac_service import sync_rbac

settings = get_settings()


def init_db() -> None:
    """Dev bootstrap: create tables + seed RBAC catalog + seed FAO-56 crop knowledge.

    Production uses Alembic migrations (`alembic upgrade head`); AUTO_CREATE_TABLES
    should be False there.
    """
    register_all_models()
    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        sync_rbac(db)
        seed_standard_crop_database(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # --- Phase 2 Module 9 device channel ---------------------------------
    # In-process fallback bus: ALWAYS subscribed, identical topic schema and
    # pub/sub contract as MQTT, so the channel works with no broker installed.
    bus = get_bus()
    bus_token = bus.subscribe(
        subscription_wildcard(settings.MQTT_BASE_TOPIC),
        make_bus_subscriber(SessionLocal, settings.MQTT_BASE_TOPIC),
    )
    # Real broker subscriber when configured AND actually reachable.
    mqtt_sub = start_if_enabled(SessionLocal)
    app.state.mqtt_subscriber = mqtt_sub
    app.state.in_process_bus_active = True

    yield

    bus.unsubscribe(bus_token)
    if mqtt_sub is not None:
        mqtt_sub.stop()


app = FastAPI(
    title=f"{settings.APP_NAME} API",
    description=(
        "AgroSmart Irrigation Intelligence System — Phase 1 (Modules 1 & 2) "
        "+ Phase 2 core (Modules 5/6/9: soil & weather telemetry, device "
        "auth, sensor failure detection)."
    ),
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Uploads directory for vision images and field attachments
upload_dir = os.path.join(os.getcwd(), "uploads")
os.makedirs(upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

app.include_router(api_router)


# ---------------------------------------------------------------------------
# Error handling — consistent machine-readable envelope everywhere.
# ---------------------------------------------------------------------------

@app.exception_handler(AppError)
async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals; log server-side.
    import logging

    from sqlalchemy.exc import IntegrityError

    if isinstance(exc, IntegrityError):
        # Race-condition uniqueness clashes (services pre-check these).
        return JSONResponse(
            status_code=409,
            content={
                "error": {"code": "conflict", "message": "Resource violates a uniqueness constraint"}
            },
        )
    logging.getLogger("asiis").exception("Unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Internal server error"}},
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "request_validation_failed",
                "message": "Request body/parameters failed validation",
            },
            "details": [
                {"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()
            ],
        },
    )


@app.get("/health", tags=["Meta"])
def health() -> dict:
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
