"""TaskPilot v1.0 baseline schema.

Revision ID: 0001_v1_0
Revises:
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_v1_0"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')",
            name="ck_tasks_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tasks_status_created_at",
        "tasks",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index("ix_tasks_due_at", "tasks", ["due_at"], unique=False)

    op.create_table(
        "pending_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("result_task_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "action_type IN ('create_task', 'complete_task')",
            name="ck_pending_actions_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'confirmed', 'cancelled', 'expired')",
            name="ck_pending_actions_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pending_actions_status_expires_at",
        "pending_actions",
        ["status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pending_actions_status_expires_at", table_name="pending_actions")
    op.drop_table("pending_actions")
    op.drop_index("ix_tasks_due_at", table_name="tasks")
    op.drop_index("ix_tasks_status_created_at", table_name="tasks")
    op.drop_table("tasks")
