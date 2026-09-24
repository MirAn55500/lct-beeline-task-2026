"""seed base dictionary values (transport, skill, priority, unassigned_reason)

Revision ID: 0008_seed_dicts
Revises: 0007_personnel_page_fields
Create Date: 2026-09-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_seed_dicts"
down_revision: Union[str, Sequence[str], None] = "0007_personnel_page_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Дублируем канон здесь, чтобы миграция не зависела от импорта приложения.
_ROWS: tuple[tuple[str, str], ...] = (
    ("transport", "car"),
    ("transport", "walking"),
    ("transport", "bicycle"),
    ("transport", "public_transport"),
    ("skill", "local"),
    ("skill", "connection"),
    ("skill", "emergency"),
    ("priority", "emergency"),
    ("priority", "connection"),
    ("priority", "repair_or_addon"),
    ("unassigned_reason", "no_engineers"),
    ("unassigned_reason", "no_region"),
    ("unassigned_reason", "no_skill"),
    ("unassigned_reason", "no_transport"),
    ("unassigned_reason", "no_equipment"),
    ("unassigned_reason", "no_work_time"),
    ("unassigned_reason", "time_conflict"),
    ("unassigned_reason", "not_found"),
    ("unassigned_reason", "manual"),
)


def upgrade() -> None:
    conn = op.get_bind()
    for group, value in _ROWS:
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM dicts WHERE \"group\" = :group AND value = :value LIMIT 1"
            ),
            {"group": group, "value": value},
        ).first()
        if exists is None:
            conn.execute(
                sa.text(
                    "INSERT INTO dicts (value, \"group\") VALUES (:value, :group)"
                ),
                {"value": value, "group": group},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for group, value in _ROWS:
        conn.execute(
            sa.text(
                "DELETE FROM dicts WHERE \"group\" = :group AND value = :value"
            ),
            {"group": group, "value": value},
        )
