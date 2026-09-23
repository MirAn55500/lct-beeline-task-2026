"""add region to plans

Revision ID: 0005_plan_region
Revises: 0004_seed_moscow_regions
Create Date: 2026-09-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_plan_region"
down_revision: Union[str, Sequence[str], None] = "0004_seed_moscow_regions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("region_id", sa.Integer(), nullable=False))
    op.create_foreign_key(
        "fk_plans_region_id_regions",
        "plans",
        "regions",
        ["region_id"],
        ["region_id"],
    )
    op.create_index("ix_plans_region_id", "plans", ["region_id"])


def downgrade() -> None:
    op.drop_index("ix_plans_region_id", table_name="plans")
    op.drop_constraint("fk_plans_region_id_regions", "plans", type_="foreignkey")
    op.drop_column("plans", "region_id")
