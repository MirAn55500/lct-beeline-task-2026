"""transit profiles (rRAPTOR) for public transport

Revision ID: 0009_transit_profiles
Revises: 0008_seed_dicts
Create Date: 2026-09-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_transit_profiles"
down_revision: Union[str, Sequence[str], None] = "0008_seed_dicts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transit_feed",
        sa.Column("feed_version", sa.String(16), primary_key=True),
        sa.Column("first_second", sa.Integer(), nullable=False),
        sa.Column("last_second", sa.Integer(), nullable=False),
        sa.Column("pairs", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
    )
    op.create_table(
        "transit_profile",
        sa.Column("feed_version", sa.String(16), primary_key=True),
        sa.Column("weekday", sa.SmallInteger(), primary_key=True),
        sa.Column("origin", sa.String(32), primary_key=True),
        sa.Column("dest", sa.String(32), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("transit_profile")
    op.drop_table("transit_feed")
