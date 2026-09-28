"""plans.snapshot: a plan version is stored as it was shown, later edits of tickets don't change it

Revision ID: 0016_plan_snapshot
Revises: 0015_assignment_window
Create Date: 2026-09-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_plan_snapshot"
down_revision: Union[str, Sequence[str], None] = "0015_assignment_window"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("snapshot", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "snapshot")
