"""engineers.planning_enabled — постоянный допуск к планированию

Revision ID: 0020_engineer_planning
Revises: 0019_plan_baseline
Create Date: 2026-09-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_engineer_planning"
down_revision: Union[str, Sequence[str], None] = "0019_plan_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "engineers",
        sa.Column(
            "planning_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("engineers", "planning_enabled")
