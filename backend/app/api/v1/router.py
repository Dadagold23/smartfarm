from fastapi import APIRouter

from app.api.v1.routes import (
    audit,
    auth,
    crops,
    devices,
    farms,
    faults,
    plantings,
    roles,
    schedules,
    soil,
    soil_profiles,
    telemetry,
    users,
    vision,
    weather,
    zones,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(roles.router, prefix="", tags=["Roles & Permissions"])
api_router.include_router(farms.router, prefix="/farms", tags=["Farms"])
api_router.include_router(zones.router, prefix="", tags=["Irrigation Zones"])
api_router.include_router(audit.router, prefix="/audit-logs", tags=["Audit"])
# Phase 2 — Modules 5/6/9: IoT + telemetry + faults
api_router.include_router(devices.router, prefix="/devices", tags=["IoT Devices"])
api_router.include_router(
    telemetry.router, prefix="/telemetry", tags=["Telemetry Ingestion"]
)
api_router.include_router(faults.router, prefix="/faults", tags=["Sensor Faults"])
api_router.include_router(soil.router, prefix="/soil", tags=["Soil Telemetry"])
api_router.include_router(weather.router, prefix="/weather", tags=["Weather Telemetry"])
# Phase 3 — Modules 3/4/7/12/19/22: Crops, Soil Profiles, Plantings, Schedules, AI Vision
api_router.include_router(crops.router, prefix="/crops", tags=["Crop Knowledge"])
api_router.include_router(soil_profiles.router, prefix="/soil-profiles", tags=["Soil Profiles"])
api_router.include_router(plantings.router, prefix="/plantings", tags=["Planting Lifecycle"])
api_router.include_router(schedules.router, prefix="/schedules", tags=["Irrigation Scheduling"])
api_router.include_router(vision.router, prefix="/vision", tags=["Crop & Weed Identification"])
