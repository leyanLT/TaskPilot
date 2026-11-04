"""TaskPilot v1.5: projects, subtasks, planning, notifications, reports.

Revision ID: 0003_v1_5
Revises: 0002_ai_upgrade
Create Date: 2026-11-03

The migration is data-preserving:

* new ``tasks`` columns are added by recreating the SQLite table through
  Alembic batch mode; existing rows are copied unchanged;
* existing completed tasks receive ``completed_at = updated_at`` so historical
  progress reporting has a truthful timestamp;
* all pre-existing pending actions and assistant messages are kept.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_v1_5"
down_revision: str | None = "0002_ai_upgrade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_ACTION_TYPES = (
    "'create_task', 'create_tasks', 'complete_task', 'update_task', "
    "'delete_task', 'batch_reschedule', 'create_task_breakdown', "
    "'save_daily_plan', 'save_report'"
)
OLD_ACTION_TYPES = (
    "'create_task', 'create_tasks', 'complete_task', 'update_task', 'delete_task', "
    "'batch_reschedule'"
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


def _create_projects() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('planning', 'active', 'completed', 'archived')",
            name="ck_projects_status",
        ),
        sa.CheckConstraint(
            "start_date IS NULL OR due_date IS NULL OR due_date >= start_date",
            name="ck_projects_dates",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_status_created_at", "projects", ["status", "created_at"])
    op.create_index("ix_projects_due_date", "projects", ["due_date"])


def _upgrade_tasks() -> None:
    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("parent_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("priority", sa.String(length=8), nullable=False, server_default="medium")
        )
        batch_op.add_column(sa.Column("estimated_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("position", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_tasks_project_id",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_tasks_parent_id",
            "tasks",
            ["parent_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            "ck_tasks_priority", "priority IN ('high', 'medium', 'low')"
        )
        batch_op.create_check_constraint(
            "ck_tasks_estimated_minutes",
            "estimated_minutes IS NULL OR "
            "(estimated_minutes >= 5 AND estimated_minutes <= 1440)",
        )
        batch_op.create_check_constraint(
            "ck_tasks_parent_not_self", "parent_id IS NULL OR parent_id <> id"
        )
        batch_op.create_index("ix_tasks_project_id", ["project_id"])
        batch_op.create_index("ix_tasks_parent_id_position", ["parent_id", "position"])
        batch_op.create_index("ix_tasks_status_priority", ["status", "priority"])
        batch_op.create_index("ix_tasks_completed_at", ["completed_at"])

    # Truthful completion timestamps for historical rows. The old schema only
    # had updated_at, so it is the best available evidence.
    op.execute(
        "UPDATE tasks SET completed_at = updated_at "
        "WHERE status = 'completed' AND completed_at IS NULL"
    )


def _create_activities() -> None:
    op.create_table(
        "task_activities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("task_title", sa.String(length=100), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("project_name", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("field", sa.String(length=32), nullable=True),
        sa.Column("old_value", sa.String(length=200), nullable=True),
        sa.Column("new_value", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "action IN ('task_created', 'task_updated', 'task_completed', "
            "'task_reopened', 'task_deleted', 'task_project_changed', "
            "'subtask_created', 'project_created', 'project_updated', "
            "'project_status_changed')",
            name="ck_task_activities_action",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_activities_project_created_at",
        "task_activities",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_task_activities_task_created_at",
        "task_activities",
        ["task_id", "created_at"],
    )
    op.create_index("ix_task_activities_created_at", "task_activities", ["created_at"])


def _create_plans() -> None:
    op.create_table(
        "daily_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("available_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "available_minutes >= 5 AND available_minutes <= 1440",
            name="ck_daily_plans_available_minutes",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_date", name="uq_daily_plans_plan_date"),
    )
    op.create_table(
        "plan_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("end_at > start_at", name="ck_plan_items_time_range"),
        sa.ForeignKeyConstraint(["plan_id"], ["daily_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_items_plan_id_position", "plan_items", ["plan_id", "position"])
    op.create_index("ix_plan_items_task_id", "plan_items", ["task_id"])


def _create_notifications() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("task_title", sa.String(length=100), nullable=True),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=140), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "type IN ('today_todo', 'due_soon', 'overdue')",
            name="ck_notifications_type",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
    )
    op.create_index(
        "ix_notifications_read_at_created_at",
        "notifications",
        ["read_at", "created_at"],
    )
    op.create_index("ix_notifications_task_id", "notifications", ["task_id"])


def _create_reports() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("project_name", sa.String(length=100), nullable=True),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("ai_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "report_type IN ('daily', 'weekly', 'project')",
            name="ck_reports_type",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_report_type_created_at", "reports", ["report_type", "created_at"])
    op.create_index("ix_reports_project_id", "reports", ["project_id"])


def upgrade() -> None:
    _create_projects()
    _upgrade_tasks()
    _create_activities()
    _create_plans()
    _create_notifications()
    _create_reports()

    # Extend the pending-action type constraint, preserving every stored action.
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
    # New action types cannot survive a downgrade; only v1.0-v1.2 types remain.
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
        WHERE action_type IN (
            'create_task', 'create_tasks', 'complete_task',
            'update_task', 'delete_task', 'batch_reschedule'
        )
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

    op.drop_index("ix_reports_project_id", table_name="reports")
    op.drop_index("ix_reports_report_type_created_at", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_notifications_task_id", table_name="notifications")
    op.drop_index("ix_notifications_read_at_created_at", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_plan_items_task_id", table_name="plan_items")
    op.drop_index("ix_plan_items_plan_id_position", table_name="plan_items")
    op.drop_table("plan_items")
    op.drop_table("daily_plans")
    op.drop_index("ix_task_activities_created_at", table_name="task_activities")
    op.drop_index("ix_task_activities_task_created_at", table_name="task_activities")
    op.drop_index("ix_task_activities_project_created_at", table_name="task_activities")
    op.drop_table("task_activities")

    with op.batch_alter_table("tasks", recreate="always") as batch_op:
        batch_op.drop_index("ix_tasks_completed_at")
        batch_op.drop_index("ix_tasks_status_priority")
        batch_op.drop_index("ix_tasks_parent_id_position")
        batch_op.drop_index("ix_tasks_project_id")
        batch_op.drop_constraint("ck_tasks_parent_not_self", type_="check")
        batch_op.drop_constraint("ck_tasks_estimated_minutes", type_="check")
        batch_op.drop_constraint("ck_tasks_priority", type_="check")
        batch_op.drop_constraint("fk_tasks_parent_id", type_="foreignkey")
        batch_op.drop_constraint("fk_tasks_project_id", type_="foreignkey")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("position")
        batch_op.drop_column("estimated_minutes")
        batch_op.drop_column("priority")
        batch_op.drop_column("parent_id")
        batch_op.drop_column("project_id")

    op.drop_index("ix_projects_due_date", table_name="projects")
    op.drop_index("ix_projects_status_created_at", table_name="projects")
    op.drop_table("projects")
