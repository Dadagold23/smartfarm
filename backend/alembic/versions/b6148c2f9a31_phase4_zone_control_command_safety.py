"""phase4 zone control and device command safety

Revision ID: b6148c2f9a31
Revises: ff9aee939d5a
Create Date: 2026-11-09 05:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6148c2f9a31"
down_revision: Union[str, None] = "ff9aee939d5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE devicetype ADD VALUE IF NOT EXISTS 'irrigation_controller'"
        )

    zone_control_mode = sa.Enum(
        "manual",
        "automatic",
        "semi_automatic",
        "scheduled",
        "sensor_triggered",
        "weather_adjusted",
        name="zonecontrolmode",
    )
    with op.batch_alter_table("irrigation_zones") as batch_op:
        batch_op.add_column(
            sa.Column(
                "control_mode",
                zone_control_mode,
                nullable=False,
                server_default="automatic",
            )
        )
        batch_op.add_column(
            sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column(
                "emergency_stop", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(sa.Column("current_flow_lpm", sa.Numeric(8, 2), nullable=True))
        batch_op.add_column(sa.Column("pressure_bar", sa.Numeric(6, 2), nullable=True))
        batch_op.add_column(sa.Column("last_started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_stopped_at", sa.DateTime(), nullable=True))

    command_status = sa.Enum(
        "queued",
        "sent",
        "acked",
        "failed",
        "expired",
        "cancelled",
        name="devicecommandstatus",
    )
    op.create_table(
        "device_commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("farm_id", sa.Integer(), nullable=False),
        sa.Column("zone_id", sa.Integer(), nullable=True),
        sa.Column("control_action", sa.String(length=32), nullable=True),
        sa.Column("command", sa.String(length=120), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", command_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("acked_at", sa.DateTime(), nullable=True),
        sa.Column("ack_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["zone_id"], ["irrigation_zones.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("device_commands") as batch_op:
        batch_op.create_index("ix_device_commands_device_id", ["device_id"])
        batch_op.create_index("ix_device_commands_farm_id", ["farm_id"])
        batch_op.create_index("ix_device_commands_zone_id", ["zone_id"])


def downgrade() -> None:
    op.drop_table("device_commands")
    with op.batch_alter_table("irrigation_zones") as batch_op:
        batch_op.drop_column("last_stopped_at")
        batch_op.drop_column("last_started_at")
        batch_op.drop_column("pressure_bar")
        batch_op.drop_column("current_flow_lpm")
        batch_op.drop_column("emergency_stop")
        batch_op.drop_column("is_running")
        batch_op.drop_column("control_mode")

