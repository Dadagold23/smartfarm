"""Model registry package."""

from app.db.base import Base, register_all_models
from app.models.audit import AuditLog  # noqa: F401
from app.models.crop import (  # noqa: F401
    CropCategory,
    CropGrowthStage,
    CropSpecies,
    GrowthStageName,
)
from app.models.farm import (  # noqa: F401
    Farm,
    FarmStatus,
    IrrigationZone,
    WaterSourceType,
    ZoneControlMode,
    ZoneStatus,
)
from app.models.iot import (  # noqa: F401
    Device,
    DeviceCommand,
    DeviceCommandStatus,
    DeviceFaultEvent,
    DeviceStatus,
    DeviceType,
    FaultType,
)
from app.models.planting import (  # noqa: F401
    CropHealthAssessment,
    HealthRating,
    PlantingBatch,
    PlantingStatus,
    StressType,
)
from app.models.schedule import (  # noqa: F401
    IrrigationSchedule,
    ScheduleReason,
    ScheduleStatus,
)
from app.models.soil import ReadingSource, SoilReading  # noqa: F401
from app.models.soil_profile import (  # noqa: F401
    SoilProfile,
    SoilTextureType,
)
from app.models.user import Permission, Role, User, role_permissions, user_roles  # noqa: F401
from app.models.vision import (  # noqa: F401
    IdentificationType,
    PlantIdentification,
    VerificationStatus,
    WeedCompetitionRisk,
    WeedInfestationLevel,
)
from app.models.weather import (  # noqa: F401
    ObservationSource,
    WeatherForecast,
    WeatherObservation,
)

register_all_models()

__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "user_roles",
    "role_permissions",
    "Farm",
    "IrrigationZone",
    "FarmStatus",
    "ZoneStatus",
    "ZoneControlMode",
    "WaterSourceType",
    "AuditLog",
    "Device",
    "DeviceCommand",
    "DeviceCommandStatus",
    "DeviceFaultEvent",
    "DeviceStatus",
    "DeviceType",
    "FaultType",
    "SoilReading",
    "ReadingSource",
    "WeatherObservation",
    "WeatherForecast",
    "ObservationSource",
    # Phase 3
    "SoilProfile",
    "SoilTextureType",
    "CropSpecies",
    "CropGrowthStage",
    "CropCategory",
    "GrowthStageName",
    "PlantingBatch",
    "PlantingStatus",
    "CropHealthAssessment",
    "HealthRating",
    "StressType",
    "IrrigationSchedule",
    "ScheduleStatus",
    "ScheduleReason",
    "PlantIdentification",
    "IdentificationType",
    "WeedInfestationLevel",
    "WeedCompetitionRisk",
    "VerificationStatus",
]
