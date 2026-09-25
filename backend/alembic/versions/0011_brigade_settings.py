"""brigade settings: work days, planning switch and served areas

Revision ID: 0011_brigade_settings
Revises: 0010_assignment_schedule
Create Date: 2026-09-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_brigade_settings"
down_revision: Union[str, Sequence[str], None] = "0010_assignment_schedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Все дни недели — чтобы уже загруженные заявки на выходные планировались как раньше
    op.add_column(
        "brigades",
        sa.Column("work_days", sa.String(), nullable=False, server_default="1234567"),
    )
    op.add_column(
        "brigades",
        sa.Column("in_planning", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_table(
        "brigade_areas",
        sa.Column("brigade_id", sa.Integer(), sa.ForeignKey("brigades.brigade_id"), primary_key=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), primary_key=True),
    )
    # Бригада в регионе одна — она и обслуживает все его районы, кроме служебного «Офис»
    op.execute(
        """
        INSERT INTO brigade_areas (brigade_id, area_id)
        SELECT b.brigade_id, a.id
        FROM brigades AS b
        JOIN areas AS a ON a.region_id = b.region_id
        WHERE a.area <> 'Офис'
        """
    )


def downgrade() -> None:
    op.drop_table("brigade_areas")
    op.drop_column("brigades", "in_planning")
    op.drop_column("brigades", "work_days")
