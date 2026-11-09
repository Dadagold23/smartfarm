"""Module 4 — Agricultural Research and Crop Knowledge Repository Service.

Provides verified crop agronomic parameters (FAO-56 Kc coefficients, root depths,
depletion fractions, GDD parameters) and soil profile physical management.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.crop import CropCategory, CropGrowthStage, CropSpecies, GrowthStageName
from app.models.soil_profile import USDA_SOIL_DEFAULTS, SoilProfile, SoilTextureType
from app.services.audit_service import record_audit_event


# ---------------------------------------------------------------------------
# Verified FAO-56 research crop dataset
# ---------------------------------------------------------------------------
FAO_56_STANDARD_CROPS: list[dict] = [
    {
        "common_name": "Maize",
        "scientific_name": "Zea mays",
        "category": CropCategory.cereal,
        "variety": "Standard Hybrid",
        "description": "Warm-season cereal grain with high water demand during pollination and grain fill.",
        "min_root_depth_m": Decimal("0.80"),
        "max_root_depth_m": Decimal("1.20"),
        "depletion_fraction_p": Decimal("0.55"),
        "yield_response_factor_ky": Decimal("1.25"),
        "base_temperature_c": Decimal("10.0"),
        "cutoff_temperature_c": Decimal("30.0"),
        "standard_cycle_days": 125,
        "optimal_ph_min": Decimal("5.80"),
        "optimal_ph_max": Decimal("7.00"),
        "salinity_threshold_ec_ds_m": Decimal("1.70"),
        "research_source": "FAO Irrigation and Drainage Paper 56, Table 12 & 22",
        "stages": [
            {"stage_name": GrowthStageName.initial, "stage_order": 1, "duration_days": 20, "kc": Decimal("0.40"), "root_m": Decimal("0.80")},
            {"stage_name": GrowthStageName.development, "stage_order": 2, "duration_days": 35, "kc": Decimal("0.75"), "root_m": Decimal("1.00")},
            {"stage_name": GrowthStageName.mid_season, "stage_order": 3, "duration_days": 40, "kc": Decimal("1.20"), "root_m": Decimal("1.20")},
            {"stage_name": GrowthStageName.late_season, "stage_order": 4, "duration_days": 30, "kc": Decimal("0.60"), "root_m": Decimal("1.20")},
        ],
    },
    {
        "common_name": "Tomato",
        "scientific_name": "Solanum lycopersicum",
        "category": CropCategory.vegetable,
        "variety": "Determinate / Processing",
        "description": "Sensitive to water deficit during flowering and fruit setting. High quality response to moisture management.",
        "min_root_depth_m": Decimal("0.70"),
        "max_root_depth_m": Decimal("1.00"),
        "depletion_fraction_p": Decimal("0.40"),
        "yield_response_factor_ky": Decimal("1.05"),
        "base_temperature_c": Decimal("10.0"),
        "cutoff_temperature_c": Decimal("35.0"),
        "standard_cycle_days": 135,
        "optimal_ph_min": Decimal("6.00"),
        "optimal_ph_max": Decimal("6.80"),
        "salinity_threshold_ec_ds_m": Decimal("2.50"),
        "research_source": "FAO Irrigation and Drainage Paper 56, Table 12 & 22",
        "stages": [
            {"stage_name": GrowthStageName.initial, "stage_order": 1, "duration_days": 30, "kc": Decimal("0.60"), "root_m": Decimal("0.70")},
            {"stage_name": GrowthStageName.development, "stage_order": 2, "duration_days": 40, "kc": Decimal("0.85"), "root_m": Decimal("0.85")},
            {"stage_name": GrowthStageName.mid_season, "stage_order": 3, "duration_days": 45, "kc": Decimal("1.15"), "root_m": Decimal("1.00")},
            {"stage_name": GrowthStageName.late_season, "stage_order": 4, "duration_days": 20, "kc": Decimal("0.80"), "root_m": Decimal("1.00")},
        ],
    },
    {
        "common_name": "Wheat (Spring)",
        "scientific_name": "Triticum aestivum",
        "category": CropCategory.cereal,
        "variety": "Semi-dwarf Spring",
        "description": "Cool-season grain crop. Critical moisture stages are stem elongation and anthesis.",
        "min_root_depth_m": Decimal("0.90"),
        "max_root_depth_m": Decimal("1.50"),
        "depletion_fraction_p": Decimal("0.55"),
        "yield_response_factor_ky": Decimal("1.15"),
        "base_temperature_c": Decimal("5.0"),
        "cutoff_temperature_c": Decimal("30.0"),
        "standard_cycle_days": 120,
        "optimal_ph_min": Decimal("6.00"),
        "optimal_ph_max": Decimal("7.50"),
        "salinity_threshold_ec_ds_m": Decimal("6.00"),
        "research_source": "FAO Irrigation and Drainage Paper 56, Table 12 & 22",
        "stages": [
            {"stage_name": GrowthStageName.initial, "stage_order": 1, "duration_days": 20, "kc": Decimal("0.30"), "root_m": Decimal("0.90")},
            {"stage_name": GrowthStageName.development, "stage_order": 2, "duration_days": 30, "kc": Decimal("0.75"), "root_m": Decimal("1.20")},
            {"stage_name": GrowthStageName.mid_season, "stage_order": 3, "duration_days": 45, "kc": Decimal("1.15"), "root_m": Decimal("1.50")},
            {"stage_name": GrowthStageName.late_season, "stage_order": 4, "duration_days": 25, "kc": Decimal("0.40"), "root_m": Decimal("1.50")},
        ],
    },
    {
        "common_name": "Potato",
        "scientific_name": "Solanum tuberosum",
        "category": CropCategory.tuber,
        "variety": "Russet / Table",
        "description": "Shallow-rooted, highly drought-sensitive crop. Requires frequent, light irrigations.",
        "min_root_depth_m": Decimal("0.40"),
        "max_root_depth_m": Decimal("0.60"),
        "depletion_fraction_p": Decimal("0.35"),
        "yield_response_factor_ky": Decimal("1.10"),
        "base_temperature_c": Decimal("7.0"),
        "cutoff_temperature_c": Decimal("28.0"),
        "standard_cycle_days": 115,
        "optimal_ph_min": Decimal("5.00"),
        "optimal_ph_max": Decimal("6.50"),
        "salinity_threshold_ec_ds_m": Decimal("1.70"),
        "research_source": "FAO Irrigation and Drainage Paper 56, Table 12 & 22",
        "stages": [
            {"stage_name": GrowthStageName.initial, "stage_order": 1, "duration_days": 25, "kc": Decimal("0.50"), "root_m": Decimal("0.40")},
            {"stage_name": GrowthStageName.development, "stage_order": 2, "duration_days": 30, "kc": Decimal("0.80"), "root_m": Decimal("0.50")},
            {"stage_name": GrowthStageName.mid_season, "stage_order": 3, "duration_days": 45, "kc": Decimal("1.15"), "root_m": Decimal("0.60")},
            {"stage_name": GrowthStageName.late_season, "stage_order": 4, "duration_days": 15, "kc": Decimal("0.75"), "root_m": Decimal("0.60")},
        ],
    },
    {
        "common_name": "Soybean",
        "scientific_name": "Glycine max",
        "category": CropCategory.legume,
        "variety": "Maturity Group III/IV",
        "description": "Nitrogen-fixing grain legume. Peak water consumption occurs at flowering and pod development.",
        "min_root_depth_m": Decimal("0.60"),
        "max_root_depth_m": Decimal("1.30"),
        "depletion_fraction_p": Decimal("0.50"),
        "yield_response_factor_ky": Decimal("0.85"),
        "base_temperature_c": Decimal("10.0"),
        "cutoff_temperature_c": Decimal("32.0"),
        "standard_cycle_days": 130,
        "optimal_ph_min": Decimal("6.00"),
        "optimal_ph_max": Decimal("7.00"),
        "salinity_threshold_ec_ds_m": Decimal("5.00"),
        "research_source": "FAO Irrigation and Drainage Paper 56, Table 12 & 22",
        "stages": [
            {"stage_name": GrowthStageName.initial, "stage_order": 1, "duration_days": 20, "kc": Decimal("0.40"), "root_m": Decimal("0.60")},
            {"stage_name": GrowthStageName.development, "stage_order": 2, "duration_days": 30, "kc": Decimal("0.80"), "root_m": Decimal("1.00")},
            {"stage_name": GrowthStageName.mid_season, "stage_order": 3, "duration_days": 60, "kc": Decimal("1.15"), "root_m": Decimal("1.30")},
            {"stage_name": GrowthStageName.late_season, "stage_order": 4, "duration_days": 20, "kc": Decimal("0.50"), "root_m": Decimal("1.30")},
        ],
    },
    {
        "common_name": "Cotton",
        "scientific_name": "Gossypium hirsutum",
        "category": CropCategory.fiber,
        "variety": "Upland Cotton",
        "description": "Deep-rooted warm-season fiber crop with moderate drought tolerance and high salinity threshold.",
        "min_root_depth_m": Decimal("1.00"),
        "max_root_depth_m": Decimal("1.70"),
        "depletion_fraction_p": Decimal("0.65"),
        "yield_response_factor_ky": Decimal("0.85"),
        "base_temperature_c": Decimal("15.0"),
        "cutoff_temperature_c": Decimal("38.0"),
        "standard_cycle_days": 180,
        "optimal_ph_min": Decimal("5.80"),
        "optimal_ph_max": Decimal("8.00"),
        "salinity_threshold_ec_ds_m": Decimal("7.70"),
        "research_source": "FAO Irrigation and Drainage Paper 56, Table 12 & 22",
        "stages": [
            {"stage_name": GrowthStageName.initial, "stage_order": 1, "duration_days": 30, "kc": Decimal("0.35"), "root_m": Decimal("1.00")},
            {"stage_name": GrowthStageName.development, "stage_order": 2, "duration_days": 50, "kc": Decimal("0.75"), "root_m": Decimal("1.40")},
            {"stage_name": GrowthStageName.mid_season, "stage_order": 3, "duration_days": 60, "kc": Decimal("1.20"), "root_m": Decimal("1.70")},
            {"stage_name": GrowthStageName.late_season, "stage_order": 4, "duration_days": 40, "kc": Decimal("0.65"), "root_m": Decimal("1.70")},
        ],
    },
    {
        "common_name": "Onion (Dry)",
        "scientific_name": "Allium cepa",
        "category": CropCategory.vegetable,
        "variety": "Long-day / Short-day Dry",
        "description": "Very shallow-rooted bulb crop with low depletion tolerance. Yield is highly sensitive to soil moisture stress.",
        "min_root_depth_m": Decimal("0.30"),
        "max_root_depth_m": Decimal("0.50"),
        "depletion_fraction_p": Decimal("0.30"),
        "yield_response_factor_ky": Decimal("1.10"),
        "base_temperature_c": Decimal("6.0"),
        "cutoff_temperature_c": Decimal("30.0"),
        "standard_cycle_days": 140,
        "optimal_ph_min": Decimal("6.00"),
        "optimal_ph_max": Decimal("7.00"),
        "salinity_threshold_ec_ds_m": Decimal("1.20"),
        "research_source": "FAO Irrigation and Drainage Paper 56, Table 12 & 22",
        "stages": [
            {"stage_name": GrowthStageName.initial, "stage_order": 1, "duration_days": 20, "kc": Decimal("0.70"), "root_m": Decimal("0.30")},
            {"stage_name": GrowthStageName.development, "stage_order": 2, "duration_days": 35, "kc": Decimal("0.90"), "root_m": Decimal("0.40")},
            {"stage_name": GrowthStageName.mid_season, "stage_order": 3, "duration_days": 60, "kc": Decimal("1.05"), "root_m": Decimal("0.50")},
            {"stage_name": GrowthStageName.late_season, "stage_order": 4, "duration_days": 25, "kc": Decimal("0.75"), "root_m": Decimal("0.50")},
        ],
    },
    {
        "common_name": "Rice (Sprinkler / Aerobic)",
        "scientific_name": "Oryza sativa",
        "category": CropCategory.cereal,
        "variety": "Upland / Aerobic Rice",
        "description": "Non-flooded sprinkler-managed rice. Shallow root system with low allowable depletion fraction.",
        "min_root_depth_m": Decimal("0.50"),
        "max_root_depth_m": Decimal("1.00"),
        "depletion_fraction_p": Decimal("0.20"),
        "yield_response_factor_ky": Decimal("1.10"),
        "base_temperature_c": Decimal("10.0"),
        "cutoff_temperature_c": Decimal("35.0"),
        "standard_cycle_days": 120,
        "optimal_ph_min": Decimal("5.50"),
        "optimal_ph_max": Decimal("7.00"),
        "salinity_threshold_ec_ds_m": Decimal("3.00"),
        "research_source": "FAO Irrigation and Drainage Paper 56, Table 12 & 22",
        "stages": [
            {"stage_name": GrowthStageName.initial, "stage_order": 1, "duration_days": 30, "kc": Decimal("1.05"), "root_m": Decimal("0.50")},
            {"stage_name": GrowthStageName.development, "stage_order": 2, "duration_days": 30, "kc": Decimal("1.10"), "root_m": Decimal("0.80")},
            {"stage_name": GrowthStageName.mid_season, "stage_order": 3, "duration_days": 40, "kc": Decimal("1.20"), "root_m": Decimal("1.00")},
            {"stage_name": GrowthStageName.late_season, "stage_order": 4, "duration_days": 20, "kc": Decimal("0.90"), "root_m": Decimal("1.00")},
        ],
    },
]


def seed_standard_crop_database(db: Session) -> int:
    """Ensure standard FAO-56 crop species and stages are populated in the database."""
    created_count = 0
    for crop_data in FAO_56_STANDARD_CROPS:
        existing = db.execute(
            select(CropSpecies).where(CropSpecies.common_name == crop_data["common_name"])
        ).scalar_one_or_none()

        if existing is None:
            stages_data = crop_data.get("stages", [])
            crop = CropSpecies(
                common_name=crop_data["common_name"],
                scientific_name=crop_data["scientific_name"],
                category=crop_data["category"],
                variety=crop_data["variety"],
                description=crop_data["description"],
                min_root_depth_m=crop_data["min_root_depth_m"],
                max_root_depth_m=crop_data["max_root_depth_m"],
                depletion_fraction_p=crop_data["depletion_fraction_p"],
                yield_response_factor_ky=crop_data["yield_response_factor_ky"],
                base_temperature_c=crop_data["base_temperature_c"],
                cutoff_temperature_c=crop_data.get("cutoff_temperature_c"),
                standard_cycle_days=crop_data["standard_cycle_days"],
                optimal_ph_min=crop_data.get("optimal_ph_min"),
                optimal_ph_max=crop_data.get("optimal_ph_max"),
                salinity_threshold_ec_ds_m=crop_data.get("salinity_threshold_ec_ds_m"),
                research_source=crop_data["research_source"],
                is_verified=True,
            )
            db.add(crop)
            db.flush()

            for s in stages_data:
                stage = CropGrowthStage(
                    crop_id=crop.id,
                    stage_name=s["stage_name"],
                    stage_order=s["stage_order"],
                    duration_days=s["duration_days"],
                    duration_pct_of_cycle=Decimal(str(round((s["duration_days"] / crop.standard_cycle_days) * 100, 2))),
                    kc_coefficient=s["kc"],
                    stage_root_depth_m=s.get("root_m"),
                    description=f"{s['stage_name'].value.replace('_', ' ').title()} stage for {crop.common_name}",
                )
                db.add(stage)

            created_count += 1

    if created_count > 0:
        db.commit()

    total_count = db.execute(
        select(func.count()).select_from(CropSpecies).where(CropSpecies.is_deleted.is_(False))
    ).scalar() or 0
    return total_count


def list_crop_species(
    db: Session,
    category: CropCategory | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[Sequence[CropSpecies], int]:
    """List crop knowledge entries with optional category filtering and search."""
    stmt = select(CropSpecies).where(CropSpecies.is_deleted.is_(False))
    if category is not None:
        stmt = stmt.where(CropSpecies.category == category)
    if query:
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                CropSpecies.common_name.ilike(pattern),
                CropSpecies.scientific_name.ilike(pattern),
                CropSpecies.variety.ilike(pattern),
            )
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.execute(
        stmt.order_by(CropSpecies.common_name.asc()).limit(limit).offset(offset)
    ).scalars().all()
    return items, total


def get_crop_species_by_id(db: Session, crop_id: int) -> CropSpecies:
    """Retrieve single crop species with its growth stages."""
    crop = db.execute(
        select(CropSpecies).where(CropSpecies.id == crop_id, CropSpecies.is_deleted.is_(False))
    ).scalar_one_or_none()
    if crop is None:
        raise NotFoundError("CropSpecies", str(crop_id))
    return crop


# ---------------------------------------------------------------------------
# Soil Profile Services
# ---------------------------------------------------------------------------

def create_soil_profile(
    db: Session,
    farm_id: int,
    name: str,
    texture_type: SoilTextureType,
    field_capacity: Decimal | None = None,
    wilting_point: Decimal | None = None,
    saturation: Decimal | None = None,
    intake_rate_mm_per_hour: Decimal | None = None,
    ph: Decimal | None = None,
    ec_ds_m: Decimal | None = None,
    description: str = "",
    actor_id: int | None = None,
    ip_address: str = "",
) -> SoilProfile:
    """Create a new soil profile, defaulting hydraulic properties from USDA tables if omitted."""
    # Apply defaults if not specified
    defaults = USDA_SOIL_DEFAULTS.get(texture_type, (Decimal("0.27"), Decimal("0.12"), Decimal("13.0")))
    fc = field_capacity if field_capacity is not None else defaults[0]
    wp = wilting_point if wilting_point is not None else defaults[1]
    intake = intake_rate_mm_per_hour if intake_rate_mm_per_hour is not None else defaults[2]

    if fc <= wp:
        raise ValidationError("Field capacity must be greater than wilting point")

    profile = SoilProfile(
        farm_id=farm_id,
        name=name.strip(),
        texture_type=texture_type,
        description=description.strip(),
        field_capacity=fc,
        wilting_point=wp,
        saturation=saturation if saturation is not None else (fc + Decimal("0.19")),
        intake_rate_mm_per_hour=intake,
        ph=ph,
        electrical_conductivity_ds_m=ec_ds_m,
    )
    db.add(profile)
    db.flush()

    record_audit_event(
        db,
        action="soil_profile.create",
        resource_type="soil_profile",
        resource_id=str(profile.id),
        user_id=actor_id,
        actor_label=("system" if actor_id is None else f"user:{actor_id}"),
        details={"farm_id": farm_id, "name": name, "texture": texture_type.value},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(profile)
    return profile


def list_soil_profiles_for_farm(db: Session, farm_id: int) -> Sequence[SoilProfile]:
    """Return all active soil profiles configured for a farm."""
    return db.execute(
        select(SoilProfile)
        .where(SoilProfile.farm_id == farm_id, SoilProfile.is_deleted.is_(False))
        .order_by(SoilProfile.name.asc())
    ).scalars().all()


def get_soil_profile_by_id(db: Session, profile_id: int) -> SoilProfile:
    """Retrieve single soil profile."""
    profile = db.execute(
        select(SoilProfile).where(SoilProfile.id == profile_id, SoilProfile.is_deleted.is_(False))
    ).scalar_one_or_none()
    if profile is None:
        raise NotFoundError("SoilProfile", str(profile_id))
    return profile
