"""lunch: brigade lunch window and place, engineer overrides, lunches of a plan version

Revision ID: 0017_lunch
Revises: 0016_plan_snapshot
Create Date: 2026-09-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_lunch"
down_revision: Union[str, Sequence[str], None] = "0016_plan_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Бригада: окно обеда (по умолчанию 13–14) и где обедают — у последней заявки
    op.add_column(
        "brigades",
        sa.Column("lunch_start", sa.Time(), nullable=False, server_default=sa.text("'13:00'")),
    )
    op.add_column(
        "brigades",
        sa.Column("lunch_end", sa.Time(), nullable=False, server_default=sa.text("'14:00'")),
    )
    op.add_column(
        "brigades",
        sa.Column(
            "lunch_place",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'last_request'"),
        ),
    )
    op.add_column(
        "brigades",
        sa.Column(
            "lunch_address_id",
            sa.Integer(),
            sa.ForeignKey("addresses.address_id"),
            nullable=True,
        ),
    )
    # Инженер: пусто — как у бригады
    op.add_column("engineers", sa.Column("lunch_start", sa.Time(), nullable=True))
    op.add_column("engineers", sa.Column("lunch_end", sa.Time(), nullable=True))
    op.add_column("engineers", sa.Column("lunch_place", sa.String(length=20), nullable=True))
    op.add_column(
        "engineers",
        sa.Column(
            "lunch_address_id",
            sa.Integer(),
            sa.ForeignKey("addresses.address_id"),
            nullable=True,
        ),
    )
    # Обеды версии плана: у каждого инженера — когда и где
    op.add_column("plans", sa.Column("lunches", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "lunches")
    for column in ("lunch_address_id", "lunch_place", "lunch_end", "lunch_start"):
        op.drop_column("engineers", column)
    for column in ("lunch_address_id", "lunch_place", "lunch_end", "lunch_start"):
        op.drop_column("brigades", column)
