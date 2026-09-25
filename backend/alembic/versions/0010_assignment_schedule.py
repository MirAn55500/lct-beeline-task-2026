"""store visit schedule on assignments

Revision ID: 0010_assignment_schedule
Revises: 0009_transit_profiles
Create Date: 2026-09-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_assignment_schedule"
down_revision: Union[str, Sequence[str], None] = "0009_transit_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("position", sa.Integer()),
    ("planned_departure_at", sa.DateTime()),
    ("planned_arrival_at", sa.DateTime()),
    ("planned_start_at", sa.DateTime()),
    ("planned_end_at", sa.DateTime()),
    ("travel_minutes", sa.Float()),
    ("distance_km", sa.Float()),
    ("waiting_minutes", sa.Float()),
    ("idle_minutes", sa.Float()),
    ("explanation", sa.Text()),
)


def upgrade() -> None:
    for name, kind in _COLUMNS:
        op.add_column("assignments", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("assignments", name)
