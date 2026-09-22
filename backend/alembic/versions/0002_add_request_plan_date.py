"""add date to requests and plans

Revision ID: 0002_add_request_plan_date
Revises: 0001_initial
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_request_plan_date"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "requests",
        sa.Column(
            "date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "plans",
        sa.Column(
            "date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("plans", "date")
    op.drop_column("requests", "date")
