"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dicts",
        sa.Column("dict_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("group", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("dict_id"),
    )
    op.create_index(op.f("ix_dicts_group"), "dicts", ["group"], unique=False)

    op.create_table(
        "cities",
        sa.Column("city_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("city_name", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("city_id"),
    )

    op.create_table(
        "regions",
        sa.Column("region_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("region_name", sa.String(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["city_id"], ["cities.city_id"]),
        sa.PrimaryKeyConstraint("region_id"),
    )

    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("area", sa.String(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["region_id"], ["regions.region_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "addresses",
        sa.Column("address_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"]),
        sa.PrimaryKeyConstraint("address_id"),
    )

    op.create_table(
        "request_type_vk_skill_maps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_type_vk_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["request_type_vk_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["dicts.dict_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "brigades",
        sa.Column("brigade_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("start_work", sa.Time(), nullable=False),
        sa.Column("end_work", sa.Time(), nullable=False),
        sa.Column("office_address_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["office_address_id"], ["addresses.address_id"]),
        sa.ForeignKeyConstraint(["region_id"], ["regions.region_id"]),
        sa.PrimaryKeyConstraint("brigade_id"),
    )

    op.create_table(
        "engineers",
        sa.Column("engineer_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("start_work", sa.Time(), nullable=False),
        sa.Column("end_work", sa.Time(), nullable=False),
        sa.Column("transport_id", sa.Integer(), nullable=False),
        sa.Column("brigade_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["brigade_id"], ["brigades.brigade_id"]),
        sa.ForeignKeyConstraint(["transport_id"], ["dicts.dict_id"]),
        sa.PrimaryKeyConstraint("engineer_id"),
    )

    op.create_table(
        "engineer_skills",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("engineer_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["engineer_id"], ["engineers.engineer_id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["dicts.dict_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "engineer_equipment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("engineer_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["engineer_id"], ["engineers.engineer_id"]),
        sa.ForeignKeyConstraint(["item_id"], ["dicts.dict_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "requests",
        sa.Column("request_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address_id", sa.Integer(), nullable=False),
        sa.Column("plan_start_time", sa.DateTime(), nullable=False),
        sa.Column("plan_end_time", sa.DateTime(), nullable=False),
        sa.Column("priority_id", sa.Integer(), nullable=False),
        sa.Column("transport_id", sa.Integer(), nullable=True),
        sa.Column("status_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("request_type_vk_id", sa.Integer(), nullable=False),
        sa.Column("request_type_hd_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.address_id"]),
        sa.ForeignKeyConstraint(["priority_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["region_id"], ["regions.region_id"]),
        sa.ForeignKeyConstraint(["request_type_hd_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["request_type_vk_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["status_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["transport_id"], ["dicts.dict_id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )

    op.create_table(
        "status_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prev_status_id", sa.Integer(), nullable=False),
        sa.Column("new_status_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("status_change_dt", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["new_status_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["prev_status_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["request_id"], ["requests.request_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "upload_snapshots",
        sa.Column("snapshoot_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("upload_dt", sa.DateTime(), nullable=False),
        sa.Column("upload_type_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_type_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["file_type_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["region_id"], ["regions.region_id"]),
        sa.ForeignKeyConstraint(["upload_type_id"], ["dicts.dict_id"]),
        sa.PrimaryKeyConstraint("snapshoot_id"),
    )

    op.create_table(
        "snapshot_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshoot_id", sa.Integer(), nullable=False),
        sa.Column("action_type_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("engineer_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["action_type_id"], ["dicts.dict_id"]),
        sa.ForeignKeyConstraint(["engineer_id"], ["engineers.engineer_id"]),
        sa.ForeignKeyConstraint(["request_id"], ["requests.request_id"]),
        sa.ForeignKeyConstraint(["snapshoot_id"], ["upload_snapshots.snapshoot_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "plans",
        sa.Column("plan_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reference_plan_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["reference_plan_id"], ["plans.plan_id"]),
        sa.PrimaryKeyConstraint("plan_id"),
    )

    op.create_table(
        "assignments",
        sa.Column("assignment_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("engineer_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("transport_id", sa.Integer(), nullable=False),
        sa.Column("actual_start_time", sa.DateTime(), nullable=True),
        sa.Column("actual_end_time", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["engineer_id"], ["engineers.engineer_id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"]),
        sa.ForeignKeyConstraint(["request_id"], ["requests.request_id"]),
        sa.ForeignKeyConstraint(["transport_id"], ["dicts.dict_id"]),
        sa.PrimaryKeyConstraint("assignment_id"),
    )

    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("start_point_id", sa.Integer(), nullable=False),
        sa.Column("end_point_id", sa.Integer(), nullable=False),
        sa.Column("transport_id", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("path", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.assignment_id"]),
        sa.ForeignKeyConstraint(["end_point_id"], ["addresses.address_id"]),
        sa.ForeignKeyConstraint(["start_point_id"], ["addresses.address_id"]),
        sa.ForeignKeyConstraint(["transport_id"], ["dicts.dict_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "replan_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("event_time", sa.DateTime(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("engineer_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["engineer_id"], ["engineers.engineer_id"]),
        sa.ForeignKeyConstraint(["request_id"], ["requests.request_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    op.drop_table("replan_events")
    op.drop_table("routes")
    op.drop_table("assignments")
    op.drop_table("plans")
    op.drop_table("snapshot_items")
    op.drop_table("upload_snapshots")
    op.drop_table("status_changes")
    op.drop_table("requests")
    op.drop_table("engineer_equipment")
    op.drop_table("engineer_skills")
    op.drop_table("engineers")
    op.drop_table("brigades")
    op.drop_table("request_type_vk_skill_maps")
    op.drop_table("addresses")
    op.drop_table("areas")
    op.drop_table("regions")
    op.drop_table("cities")
    op.drop_index(op.f("ix_dicts_group"), table_name="dicts")
    op.drop_table("dicts")
