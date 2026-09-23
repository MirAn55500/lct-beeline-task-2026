"""seed Moscow and its regions

Revision ID: 0004_seed_moscow_regions
Revises: 0003_reason_external_id
Create Date: 2026-09-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_seed_moscow_regions"
down_revision: Union[str, Sequence[str], None] = "0003_reason_external_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CITY_NAME = "Москва"
TIMEZONE = "Europe/Moscow"
REGION_NAMES = ("Восток", "Юго-восток", "Югоцентр")


def upgrade() -> None:
    conn = op.get_bind()
    city_id = conn.execute(
        sa.text(
            "INSERT INTO cities (city_name, timezone) "
            "VALUES (:city_name, :timezone) RETURNING city_id"
        ),
        {"city_name": CITY_NAME, "timezone": TIMEZONE},
    ).scalar_one()

    conn.execute(
        sa.text(
            "INSERT INTO regions (region_name, city_id) "
            "VALUES (:region_name, :city_id)"
        ),
        [
            {"region_name": name, "city_id": city_id}
            for name in REGION_NAMES
        ],
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM regions "
            "WHERE city_id IN (SELECT city_id FROM cities WHERE city_name = :city_name)"
        ),
        {"city_name": CITY_NAME},
    )
    conn.execute(
        sa.text("DELETE FROM cities WHERE city_name = :city_name"),
        {"city_name": CITY_NAME},
    )
