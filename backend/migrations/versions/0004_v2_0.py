"""TaskPilot v2.0: dependencies, recurrence, focus, plan revisions, preferences.

Revision ID: 0004_v2_0
Revises: 0003_v1_5
Create Date: 2026-11-04

The migration is additive and data-preserving:

* ``tasks`` gains an optional recurrence link and occurrence date; every
  existing row keeps its values and simply has both columns set to NULL;
* ``pending_actions`` is recreated with one extra action type (``apply_replan``)
  and all historical rows are copied over unchanged;
* no existing table, column or row is removed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_v2_0"
down_revision: str | None = "0003_v1_5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTION_TYPES = (
    "'create_task', 'create_tasks', 'complete_task', 'update_task', 'delete_task', "
    "'batch_reschedule', 'create_task_breakdown', 'save_daily_plan', 'save_report', "
    "'apply_replan'"
)
OLD_ACTION_TYPES = (
    "'create_task', 'create_tasks', 'complete_task', 'update_task', 'delete_task', "
    "'batch_reschedule', 'create_task_breakdown', 'save_daily_plan', 'save_report'"
)


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


def _rewrite_pending_actions(action_types: str) -> None:
    _create_pending_actions_table("pending_actions_v2", action_types)
    columns = (
        "id, action_type, status, payload, summary, result_task_id, created_at, "
        "expires_at, resolved_at"
    )
    op.execute(
        f"INSERT INTO pending_actions_v2 ({columns}) SELECT {columns} FROM pending_actions"
    )
    op.drop_index("ix_pending_actions_status_expires_at", table_name="pending_actions")
    op.drop_table("pending_actions")
    op.rename_table("pending_actions_v2", "pending_actions")
    op.create_index(
        "ix_pending_actions_status_expires_at",
        "pending_actions",
        ["status", "expires_at"],
        unique=False,
    )


def upgrade() -> None:
    op.create_table(
        "recurrence_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("due_time", sa.String(length=5), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly', 'custom_weekly')",
            name="ck_recurrence_rules_frequency",
        ),
        sa.CheckConstraint("interval >= 1", name="ck_recurrence_rules_interval"),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_recurrence_rules_dates",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_recurrence_rules_project_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recurrence_rules_paused_start",
        "recurrence_rules",
        ["paused", "start_date"],
        unique=False,
    )

    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("recurrence_rule_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("occurrence_date", sa.Date(), nullable=True))
        batch_op.create_foreign_key(
            "fk_tasks_recurrence_rule_id",
            "recurrence_rules",
            ["recurrence_rule_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_tasks_recurrence_occurrence",
            ["recurrence_rule_id", "occurrence_date"],
        )
        batch_op.create_index("ix_tasks_recurrence_rule_id", ["recurrence_rule_id"])

    op.create_table(
        "task_dependencies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("depends_on_task_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "task_id <> depends_on_task_id",
            name="ck_task_dependencies_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_task_dependencies_task_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_task_id"], ["tasks.id"],
            name="fk_task_dependencies_depends_on",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "depends_on_task_id", name="uq_task_dependencies_pair"
        ),
    )
    op.create_index(
        "ix_task_dependencies_task_id", "task_dependencies", ["task_id"], unique=False
    )
    op.create_index(
        "ix_task_dependencies_depends_on",
        "task_dependencies",
        ["depends_on_task_id"],
        unique=False,
    )

    op.create_table(
        "focus_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=True),
        sa.Column("accumulated_seconds", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_resumed_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'paused', 'completed', 'cancelled')",
            name="ck_focus_sessions_status",
        ),
        sa.CheckConstraint("accumulated_seconds >= 0", name="ck_focus_sessions_seconds"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_focus_sessions_task_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_focus_sessions_task_started",
        "focus_sessions",
        ["task_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_focus_sessions_started_at", "focus_sessions", ["started_at"], unique=False
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_focus_sessions_active "
        "ON focus_sessions ((status IN ('running', 'paused'))) "
        "WHERE status IN ('running', 'paused')"
    )

    op.create_table(
        "plan_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("before_items", sa.JSON(), nullable=False),
        sa.Column("after_items", sa.JSON(), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "source IN ('agent', 'user', 'system')",
            name="ck_plan_revisions_source",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_date", "revision_no", name="uq_plan_revisions_date_no"),
    )
    op.create_index(
        "ix_plan_revisions_plan_date", "plan_revisions", ["plan_date"], unique=False
    )

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("daily_available_minutes", sa.Integer(), nullable=False),
        sa.Column("workdays", sa.JSON(), nullable=True),
        sa.Column("default_focus_minutes", sa.Integer(), nullable=False),
        sa.Column("reminder_prefs", sa.JSON(), nullable=True),
        sa.Column("dismissed_insights", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "daily_available_minutes >= 5 AND daily_available_minutes <= 1440",
            name="ck_user_preferences_minutes",
        ),
        sa.CheckConstraint(
            "default_focus_minutes >= 5 AND default_focus_minutes <= 240",
            name="ck_user_preferences_focus",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    _rewrite_pending_actions(ACTION_TYPES)


def downgrade() -> None:
    _rewrite_pending_actions(OLD_ACTION_TYPES)

    op.drop_table("user_preferences")
    op.drop_index("ix_plan_revisions_plan_date", table_name="plan_revisions")
    op.drop_table("plan_revisions")
    op.execute("DROP INDEX uq_focus_sessions_active")
    op.drop_index("ix_focus_sessions_started_at", table_name="focus_sessions")
    op.drop_index("ix_focus_sessions_task_started", table_name="focus_sessions")
    op.drop_table("focus_sessions")
    op.drop_index("ix_task_dependencies_depends_on", table_name="task_dependencies")
    op.drop_index("ix_task_dependencies_task_id", table_name="task_dependencies")
    op.drop_table("task_dependencies")

    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.drop_index("ix_tasks_recurrence_rule_id")
        batch_op.drop_constraint("uq_tasks_recurrence_occurrence", type_="unique")
        batch_op.drop_constraint("fk_tasks_recurrence_rule_id", type_="foreignkey")
        batch_op.drop_column("occurrence_date")
        batch_op.drop_column("recurrence_rule_id")

    op.drop_index("ix_recurrence_rules_paused_start", table_name="recurrence_rules")
    op.drop_table("recurrence_rules")
