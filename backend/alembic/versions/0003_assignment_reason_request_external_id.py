"""add request external_id and assignment unassigned_reason

Revision ID: 0003_reason_external_id
Revises: 0002_add_request_plan_date
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_reason_external_id"
down_revision: Union[str, Sequence[str], None] = "0002_add_request_plan_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("external_id", sa.String(), nullable=False))

    op.alter_column(
        "assignments",
        "engineer_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "assignments",
        "transport_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        "assignments",
        sa.Column("unassigned_reason_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_assignments_unassigned_reason_id_dicts",
        "assignments",
        "dicts",
        ["unassigned_reason_id"],
        ["dict_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_assignments_unassigned_reason_id_dicts",
        "assignments",
        type_="foreignkey",
    )
    op.drop_column("assignments", "unassigned_reason_id")
    op.alter_column(
        "assignments",
        "transport_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "assignments",
        "engineer_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("requests", "external_id")
