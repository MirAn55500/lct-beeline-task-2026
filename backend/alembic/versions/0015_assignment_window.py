"""store client window on assignments: plan versions keep the window they were built with

Revision ID: 0015_assignment_window
Revises: 0014_drop_brigade_in_planning
Create Date: 2026-09-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_assignment_window"
down_revision: Union[str, Sequence[str], None] = "0014_drop_brigade_in_planning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("window_start", "window_end")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("assignments", sa.Column(name, sa.DateTime(), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("assignments", name)
