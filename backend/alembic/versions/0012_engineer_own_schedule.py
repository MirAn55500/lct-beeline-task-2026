"""engineer own schedule: hours follow the brigade unless set individually

Revision ID: 0012_engineer_own_schedule
Revises: 0011_brigade_settings
Create Date: 2026-09-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_engineer_own_schedule"
down_revision: Union[str, Sequence[str], None] = "0011_brigade_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "engineers",
        sa.Column("own_schedule", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Своя смена — у тех, чьи часы уже расходятся с рабочим днём бригады
    op.execute(
        """
        UPDATE engineers AS e
        SET own_schedule = true
        FROM brigades AS b
        WHERE b.brigade_id = e.brigade_id
          AND (e.start_work <> b.start_work OR e.end_work <> b.end_work)
        """
    )


def downgrade() -> None:
    op.drop_column("engineers", "own_schedule")
