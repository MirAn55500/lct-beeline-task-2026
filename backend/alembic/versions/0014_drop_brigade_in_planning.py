"""drop brigades.in_planning: brigade takes part in planning on its work days

Revision ID: 0014_drop_brigade_in_planning
Revises: 0013_engineer_profile
Create Date: 2026-09-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_drop_brigade_in_planning"
down_revision: Union[str, Sequence[str], None] = "0013_engineer_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("brigades", "in_planning")


def downgrade() -> None:
    op.add_column(
        "brigades",
        sa.Column("in_planning", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
