"""TaskPilot v2.0.1: allow the ``create_project`` pending action.

Revision ID: 0005_v2_1
Revises: 0004_v2_0
Create Date: 2026-11-04

``pending_actions`` carries a CHECK constraint on ``action_type``; the table is
recreated with one extra value and every existing row is copied unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_v2_1"
down_revision: str | None = "0004_v2_0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTION_TYPES = (
    "'create_task', 'create_tasks', 'complete_task', 'update_task', 'delete_task', "
    "'batch_reschedule', 'create_task_breakdown', 'save_daily_plan', 'save_report', "
    "'apply_replan', 'create_project'"
)
OLD_ACTION_TYPES = (
    "'create_task', 'create_tasks', 'complete_task', 'update_task', 'delete_task', "
    "'batch_reschedule', 'create_task_breakdown', 'save_daily_plan', 'save_report', "
    "'apply_replan'"
)


def _create_table(name: str, action_types: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("result_task_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(f"action_type IN ({action_types})", name="ck_pending_actions_type"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'confirmed', 'cancelled', 'expired')",
            name="ck_pending_actions_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _rewrite(action_types: str, temp_name: str) -> None:
    _create_table(temp_name, action_types)
    columns = (
        "id, action_type, status, payload, summary, result_task_id, created_at, "
        "expires_at, resolved_at"
    )
    op.execute(f"INSERT INTO {temp_name} ({columns}) SELECT {columns} FROM pending_actions")
    op.drop_index("ix_pending_actions_status_expires_at", table_name="pending_actions")
    op.drop_table("pending_actions")
    op.rename_table(temp_name, "pending_actions")
    op.create_index(
        "ix_pending_actions_status_expires_at",
        "pending_actions",
        ["status", "expires_at"],
        unique=False,
    )


def upgrade() -> None:
    _rewrite(ACTION_TYPES, "pending_actions_v3")


def downgrade() -> None:
    _rewrite(OLD_ACTION_TYPES, "pending_actions_v2d")
