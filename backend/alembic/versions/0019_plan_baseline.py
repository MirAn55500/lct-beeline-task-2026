"""plans.baseline_of_id — базовый расчёт при каждой версии плана

Revision ID: 0019_plan_baseline
Revises: 0018_plan_distribution
Create Date: 2026-09-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_plan_baseline"
down_revision: Union[str, Sequence[str], None] = "0018_plan_distribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column(
            "baseline_of_id",
            sa.Integer(),
            sa.ForeignKey("plans.plan_id"),
            nullable=True,
        ),
    )
    op.create_index("ix_plans_baseline_of_id", "plans", ["baseline_of_id"])


def downgrade() -> None:
    op.drop_index("ix_plans_baseline_of_id", table_name="plans")
    op.drop_column("plans", "baseline_of_id")
