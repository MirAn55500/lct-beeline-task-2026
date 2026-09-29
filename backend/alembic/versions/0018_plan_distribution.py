"""plans.distribution — even / efficient for compare badges

Revision ID: 0018_plan_distribution
Revises: 0017_lunch
Create Date: 2026-09-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_plan_distribution"
down_revision: Union[str, Sequence[str], None] = "0017_lunch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("distribution", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plans", "distribution")
