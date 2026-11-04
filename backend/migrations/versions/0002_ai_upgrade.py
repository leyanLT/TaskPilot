"""AI conversation history and expanded confirmed actions.

Revision ID: 0002_ai_upgrade
Revises: 0001_v1_0
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ai_upgrade"
down_revision: str | None = "0001_v1_0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_ACTION_TYPES = (
    "'create_task', 'create_tasks', 'complete_task', "
    "'update_task', 'delete_task', 'batch_reschedule'"
)
OLD_ACTION_TYPES = "'create_task', 'complete_task'"


def _create_pending_actions_table(name: str, action_types: str) -> None:
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
        sa.CheckConstraint(
            f"action_type IN ({action_types})",
            name="ck_pending_actions_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'confirmed', 'cancelled', 'expired')",
            name="ck_pending_actions_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def upgrade() -> None:
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_assistant_messages_role",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_messages_created_at",
        "assistant_messages",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_assistant_messages_action_id",
        "assistant_messages",
        ["action_id"],
        unique=False,
    )

    # SQLite cannot alter a CHECK constraint in place. Recreate the table and
    # copy existing actions so the v1.0 data and its history are preserved.
    _create_pending_actions_table("pending_actions_new", NEW_ACTION_TYPES)
    op.execute(
        """
        INSERT INTO pending_actions_new (
            id, action_type, status, payload, summary, result_task_id,
            created_at, expires_at, resolved_at
        )
        SELECT
            id, action_type, status, payload, summary, result_task_id,
            created_at, expires_at, resolved_at
        FROM pending_actions
        """
    )
    op.drop_table("pending_actions")
    op.rename_table("pending_actions_new", "pending_actions")
    op.create_index(
        "ix_pending_actions_status_expires_at",
        "pending_actions",
        ["status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    # Downgrade is intentionally data-preserving for old action types only.
    # New action types must be resolved or removed before a v1.0 downgrade.
    _create_pending_actions_table("pending_actions_old", OLD_ACTION_TYPES)
    op.execute(
        """
        INSERT INTO pending_actions_old (
            id, action_type, status, payload, summary, result_task_id,
            created_at, expires_at, resolved_at
        )
        SELECT
            id, action_type, status, payload, summary, result_task_id,
            created_at, expires_at, resolved_at
        FROM pending_actions
        """
    )
    op.drop_table("pending_actions")
    op.rename_table("pending_actions_old", "pending_actions")
    op.create_index(
        "ix_pending_actions_status_expires_at",
        "pending_actions",
        ["status", "expires_at"],
        unique=False,
    )
    op.drop_index("ix_assistant_messages_action_id", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_created_at", table_name="assistant_messages")
    op.drop_table("assistant_messages")
