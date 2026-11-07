"""SQLAlchemy declarative base and model registry.

PostGIS note: production deployments use the `geoalchemy2`-backed columns
behind the `is_postgres` flag in alembic/env.py. For Phase 1 the spatial
reference of a farm is stored as plain lat/lon + optional GeoJSON `geometry`
text, which is sufficient for zone mapping and keeps the SQLite dev path
dependency-free. The Alembic migration adds a `geometry` column as text on
SQLite and (Phase 6) as `GEOGRAPHY(MULTIPOLYGON, 4326)` on PostgreSQL.
"""

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[str] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# imported for alembic autogenerate registry
def register_all_models() -> None:  # pragma: no cover - registry helper
    import app.models.user  # noqa: F401
    import app.models.farm  # noqa: F401
    import app.models.audit  # noqa: F401
    import app.models.iot  # noqa: F401  (Phase 2: devices + fault events)
    import app.models.soil  # noqa: F401  (Phase 2: Module 5 readings)
    import app.models.weather  # noqa: F401  (Phase 2: Module 6 obs/forecasts)
