"""SQLAlchemy ORM models.

V1.5 extends the v1.0 task table in place and adds projects, subtasks,
activities, daily plans, notifications, and reports. Existing columns and
indexes are preserved so v1.0 data keeps working after the migration.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utc_now


def new_uuid() -> str:
    return str(uuid4())


TASK_STATUSES = ("pending", "completed")
TASK_PRIORITIES = ("high", "medium", "low")
PROJECT_STATUSES = ("planning", "active", "completed", "archived")
ACTIVITY_ACTIONS = (
    "task_created",
    "task_updated",
    "task_completed",
    "task_reopened",
    "task_deleted",
    "task_project_changed",
    "subtask_created",
    "project_created",
    "project_updated",
    "project_status_changed",
)
NOTIFICATION_TYPES = ("today_todo", "due_soon", "overdue")
REPORT_TYPES = ("daily", "weekly", "project")
ACTION_TYPES = (
    "create_task",
    "create_tasks",
    "complete_task",
    "update_task",
    "delete_task",
    "batch_reschedule",
    "create_task_breakdown",
    "save_daily_plan",
    "save_report",
    "apply_replan",
    "create_project",
)

# V2.0 additions ---------------------------------------------------------------
RECURRENCE_FREQUENCIES = ("daily", "weekly", "monthly", "custom_weekly")
FOCUS_STATUSES = ("running", "paused", "completed", "cancelled")
PLAN_REVISION_SOURCES = ("agent", "user", "system")


def _in_clause(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_clause(PROJECT_STATUSES)})",
            name="ck_projects_status",
        ),
        CheckConstraint(
            "start_date IS NULL OR due_date IS NULL OR due_date >= start_date",
            name="ck_projects_dates",
        ),
        Index("ix_projects_status_created_at", "status", "created_at"),
        Index("ix_projects_due_date", "due_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planning")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'completed')", name="ck_tasks_status"),
        CheckConstraint(
            f"priority IN ({_in_clause(TASK_PRIORITIES)})",
            name="ck_tasks_priority",
        ),
        CheckConstraint(
            "estimated_minutes IS NULL OR (estimated_minutes >= 5 AND estimated_minutes <= 1440)",
            name="ck_tasks_estimated_minutes",
        ),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="ck_tasks_parent_not_self",
        ),
        Index("ix_tasks_status_created_at", "status", "created_at"),
        Index("ix_tasks_due_at", "due_at"),
        Index("ix_tasks_project_id", "project_id"),
        Index("ix_tasks_parent_id_position", "parent_id", "position"),
        Index("ix_tasks_status_priority", "status", "priority"),
        Index("ix_tasks_completed_at", "completed_at"),
        Index("ix_tasks_recurrence_rule_id", "recurrence_rule_id"),
        UniqueConstraint(
            "recurrence_rule_id",
            "occurrence_date",
            name="uq_tasks_recurrence_occurrence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
    )
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="medium")
    estimated_minutes: Mapped[int | None] = mapped_column(nullable=True)
    position: Mapped[int] = mapped_column(nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    recurrence_rule_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("recurrence_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    occurrence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class TaskActivity(Base):
    __tablename__ = "task_activities"
    __table_args__ = (
        CheckConstraint(
            f"action IN ({_in_clause(ACTIVITY_ACTIONS)})",
            name="ck_task_activities_action",
        ),
        Index("ix_task_activities_project_created_at", "project_id", "created_at"),
        Index("ix_task_activities_task_created_at", "task_id", "created_at"),
        Index("ix_task_activities_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # Activity is an append-only audit log: task/project identifiers are kept as
    # snapshots even after the referenced row is deleted, so no foreign keys
    # (which would null them out) are used here.
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    task_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    field: Mapped[str | None] = mapped_column(String(32), nullable=True)
    old_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class DailyPlan(Base):
    __tablename__ = "daily_plans"
    __table_args__ = (
        CheckConstraint(
            "available_minutes >= 5 AND available_minutes <= 1440",
            name="ck_daily_plans_available_minutes",
        ),
        UniqueConstraint("plan_date", name="uq_daily_plans_plan_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    available_minutes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class PlanItem(Base):
    __tablename__ = "plan_items"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_plan_items_time_range"),
        Index("ix_plan_items_plan_id_position", "plan_id", "position"),
        Index("ix_plan_items_task_id", "task_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("daily_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    position: Mapped[int] = mapped_column(nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            f"type IN ({_in_clause(NOTIFICATION_TYPES)})",
            name="ck_notifications_type",
        ),
        UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
        Index("ix_notifications_read_at_created_at", "read_at", "created_at"),
        Index("ix_notifications_task_id", "task_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    task_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
    )
    task_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(140), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            f"report_type IN ({_in_clause(REPORT_TYPES)})",
            name="ck_reports_type",
        ),
        Index("ix_reports_report_type_created_at", "report_type", "created_at"),
        Index("ix_reports_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    period_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    facts: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    ai_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class PendingAction(Base):
    __tablename__ = "pending_actions"
    __table_args__ = (
        CheckConstraint(
            f"action_type IN ({_in_clause(ACTION_TYPES)})",
            name="ck_pending_actions_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'confirmed', 'cancelled', 'expired')",
            name="ck_pending_actions_status",
        ),
        Index("ix_pending_actions_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    result_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_assistant_messages_role"),
        Index("ix_assistant_messages_created_at", "created_at"),
        Index("ix_assistant_messages_action_id", "action_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    candidates: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class TaskDependency(Base):
    """``task_id`` cannot start before ``depends_on_task_id`` is completed."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "depends_on_task_id",
            name="uq_task_dependencies_pair",
        ),
        CheckConstraint(
            "task_id <> depends_on_task_id",
            name="ck_task_dependencies_not_self",
        ),
        Index("ix_task_dependencies_task_id", "task_id"),
        Index("ix_task_dependencies_depends_on", "depends_on_task_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class RecurrenceRule(Base):
    """Template that materialises one task per occurrence, idempotently."""

    __tablename__ = "recurrence_rules"
    __table_args__ = (
        CheckConstraint(
            f"frequency IN ({_in_clause(RECURRENCE_FREQUENCIES)})",
            name="ck_recurrence_rules_frequency",
        ),
        CheckConstraint("interval >= 1", name="ck_recurrence_rules_interval"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_recurrence_rules_dates",
        ),
        Index("ix_recurrence_rules_paused_start", "paused", "start_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="medium")
    estimated_minutes: Mapped[int | None] = mapped_column(nullable=True)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    interval: Mapped[int] = mapped_column(nullable=False, default=1)
    weekdays: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class FocusSession(Base):
    """Server-authoritative focus timer; elapsed time is derived, not trusted."""

    __tablename__ = "focus_sessions"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_clause(FOCUS_STATUSES)})",
            name="ck_focus_sessions_status",
        ),
        CheckConstraint("accumulated_seconds >= 0", name="ck_focus_sessions_seconds"),
        Index("ix_focus_sessions_task_started", "task_id", "started_at"),
        Index("ix_focus_sessions_started_at", "started_at"),
        Index(
            "uq_focus_sessions_active",
            text("(status IN ('running', 'paused'))"),
            unique=True,
            sqlite_where=text("status IN ('running', 'paused')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="free")
    planned_minutes: Mapped[int | None] = mapped_column(nullable=True)
    accumulated_seconds: Mapped[int] = mapped_column(nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    last_resumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class PlanRevision(Base):
    """Append-only history of daily plan changes, including what was replaced."""

    __tablename__ = "plan_revisions"
    __table_args__ = (
        UniqueConstraint("plan_date", "revision_no", name="uq_plan_revisions_date_no"),
        CheckConstraint(
            f"source IN ({_in_clause(PLAN_REVISION_SOURCES)})",
            name="ck_plan_revisions_source",
        ),
        Index("ix_plan_revisions_plan_date", "plan_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    revision_no: Mapped[int] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    before_items: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    after_items: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class UserPreference(Base):
    """Single-row settings for this local, single-user application."""

    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint(
            "daily_available_minutes >= 5 AND daily_available_minutes <= 1440",
            name="ck_user_preferences_minutes",
        ),
        CheckConstraint(
            "default_focus_minutes >= 5 AND default_focus_minutes <= 240",
            name="ck_user_preferences_focus",
        ),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="default")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    daily_available_minutes: Mapped[int] = mapped_column(nullable=False, default=300)
    workdays: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    default_focus_minutes: Mapped[int] = mapped_column(nullable=False, default=25)
    reminder_prefs: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    dismissed_insights: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )
