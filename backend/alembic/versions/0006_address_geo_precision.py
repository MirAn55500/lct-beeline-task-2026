"""add geocoding precision and source to addresses

Revision ID: 0006_address_geo_precision
Revises: 0005_plan_region
Create Date: 2026-09-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_address_geo_precision"
down_revision: Union[str, Sequence[str], None] = "0005_plan_region"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("addresses", sa.Column("geo_precision", sa.String(), nullable=True))
    op.add_column("addresses", sa.Column("geo_source", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("addresses", "geo_source")
    op.drop_column("addresses", "geo_precision")
