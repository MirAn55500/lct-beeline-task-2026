"""brigade name/number and engineer qualification/is_lead for personnel page

Revision ID: 0007_personnel_page_fields
Revises: 0006_address_geo_precision
Create Date: 2026-09-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_personnel_page_fields"
down_revision: Union[str, Sequence[str], None] = "0006_address_geo_precision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brigades",
        sa.Column("name", sa.String(), nullable=False, server_default="Бригада"),
    )
    op.add_column(
        "brigades",
        sa.Column("number", sa.String(), nullable=False, server_default="01"),
    )
    op.add_column(
        "engineers",
        sa.Column("qualification", sa.String(), nullable=True),
    )
    op.add_column(
        "engineers",
        sa.Column(
            "is_lead",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Имя бригады = имя региона, если ещё дефолт.
    op.execute(
        """
        UPDATE brigades AS b
        SET name = r.region_name
        FROM regions AS r
        WHERE b.region_id = r.region_id
          AND (b.name IS NULL OR b.name = 'Бригада')
        """
    )
    # Первый инженер бригады — бригадир; квалификация по кругу.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                engineer_id,
                brigade_id,
                ROW_NUMBER() OVER (
                    PARTITION BY brigade_id ORDER BY engineer_id
                ) AS rn
            FROM engineers
        )
        UPDATE engineers AS e
        SET
            is_lead = (ranked.rn = 1),
            qualification = CASE (ranked.rn - 1) % 3
                WHEN 0 THEN 'master'
                WHEN 1 THEN 'worker'
                ELSE 'novice'
            END
        FROM ranked
        WHERE e.engineer_id = ranked.engineer_id
        """
    )

    op.alter_column("brigades", "name", server_default=None)
    op.alter_column("brigades", "number", server_default=None)
    op.alter_column("engineers", "is_lead", server_default=None)


def downgrade() -> None:
    op.drop_column("engineers", "is_lead")
    op.drop_column("engineers", "qualification")
    op.drop_column("brigades", "number")
    op.drop_column("brigades", "name")
