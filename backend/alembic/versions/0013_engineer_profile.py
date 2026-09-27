"""engineer profile: home address and own work days

Revision ID: 0013_engineer_profile
Revises: 0012_engineer_own_schedule
Create Date: 2026-09-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_engineer_profile"
down_revision: Union[str, Sequence[str], None] = "0012_engineer_own_schedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("engineers", sa.Column("home_address", sa.String(length=300), nullable=True))
    # NULL — рабочие дни бригады; строка ISO-номеров — свой график инженера
    op.add_column("engineers", sa.Column("work_days", sa.String(length=7), nullable=True))


def downgrade() -> None:
    op.drop_column("engineers", "work_days")
    op.drop_column("engineers", "home_address")
