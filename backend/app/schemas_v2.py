"""Pydantic models for TaskPilot V2.0 features.

Kept separate from the V1.5 ``schemas`` module so the older surface stays
untouched; routers import only what they need.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas import TaskPriority, TaskStatus

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


class DependencyCreate(BaseModel):
    depends_on_task_id: UUID


class DependencyRead(BaseModel):
    id: UUID
    task_id: UUID
    depends_on_task_id: UUID
    depends_on_title: str
    depends_on_status: TaskStatus
    created_at: datetime


class TaskDependenciesRead(BaseModel):
    task_id: UUID
    is_blocked: bool
    depends_on: list[DependencyRead]
    blocks: list[DependencyRead]


class BlockedTaskRead(BaseModel):
    task_id: UUID
    title: str
    blocked_by: list[str]


# ---------------------------------------------------------------------------
# Recurring tasks
# ---------------------------------------------------------------------------

Frequency = Literal["daily", "weekly", "monthly", "custom_weekly"]

DUE_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
WEEKDAYS_PATTERN = r"^[0-6](,[0-6]){0,6}$"


class RecurrenceBase(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    project_id: UUID | None = None
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: int | None = Field(default=None, ge=5, le=1440)
    frequency: Frequency
    interval: int = Field(default=1, ge=1, le=30)
    weekdays: list[int] | None = None
    start_date: date
    end_date: date | None = None
    due_time: str | None = Field(default=None, pattern=DUE_TIME_PATTERN)

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        unique = sorted({int(day) for day in value})
        if not unique or any(day < 0 or day > 6 for day in unique):
            raise ValueError("重复日期必须是 0（周一）到 6（周日）之间的数字。")
        return unique

    @model_validator(mode="after")
    def validate_dates(self) -> RecurrenceBase:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期。")
        if self.frequency == "custom_weekly" and not self.weekdays:
            raise ValueError("自定义每周重复需要至少选择一个星期。")
        if self.frequency != "custom_weekly" and self.weekdays:
            raise ValueError("只有自定义每周重复可以指定星期。")
        return self


class RecurrenceCreate(RecurrenceBase):
    pass


class RecurrenceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    project_id: UUID | None = None
    priority: TaskPriority | None = None
    estimated_minutes: int | None = Field(default=None, ge=5, le=1440)
    frequency: Frequency | None = None
    interval: int | None = Field(default=None, ge=1, le=30)
    weekdays: list[int] | None = None
    start_date: date | None = None
    end_date: date | None = None
    due_time: str | None = Field(default=None, pattern=DUE_TIME_PATTERN)
    paused: bool | None = None


class RecurrenceRead(BaseModel):
    id: UUID
    title: str
    description: str | None
    project_id: UUID | None
    priority: TaskPriority
    estimated_minutes: int | None
    frequency: Frequency
    interval: int
    weekdays: list[int] | None
    start_date: date
    end_date: date | None
    due_time: str | None
    timezone: str
    paused: bool
    next_occurrence: date | None
    generated_count: int
    completed_count: int
    pending_count: int
    created_at: datetime
    updated_at: datetime


class RecurrenceGenerateResult(BaseModel):
    created: int
    rules: int
    scanned_until: date


# ---------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------


class FocusStart(BaseModel):
    task_id: UUID
    planned_minutes: int | None = Field(default=None, ge=5, le=240)
    mode: Literal["free", "pomodoro"] = "free"
    note: str | None = Field(default=None, max_length=200)


class FocusRead(BaseModel):
    id: UUID
    task_id: UUID
    task_title: str
    task_estimated_minutes: int | None
    status: Literal["running", "paused", "completed", "cancelled"]
    mode: Literal["free", "pomodoro"]
    planned_minutes: int | None
    elapsed_seconds: int
    accumulated_seconds: int
    target_seconds: int | None
    remaining_seconds: int | None
    started_at: datetime
    last_resumed_at: datetime | None
    ended_at: datetime | None
    synced_at: datetime


class FocusDayRead(BaseModel):
    date: date
    seconds: int


class FocusTaskRead(BaseModel):
    task_id: UUID
    title: str
    seconds: int


class FocusStatsRead(BaseModel):
    today: str
    today_seconds: int
    week_seconds: int
    session_count: int
    by_day: list[FocusDayRead]
    by_task: list[FocusTaskRead]


# ---------------------------------------------------------------------------
# Calendar / time blocks
# ---------------------------------------------------------------------------


class CalendarTaskRead(BaseModel):
    id: UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    project_id: UUID | None
    is_blocked: bool
    recurrence_rule_id: UUID | None


class TimeBlockRead(BaseModel):
    id: UUID
    plan_id: UUID
    plan_date: date
    task_id: UUID
    task_title: str
    task_status: TaskStatus
    start_at: datetime
    end_at: datetime
    note: str | None
    position: int


class CalendarDayRead(BaseModel):
    date: date
    available_minutes: int
    planned_minutes: int
    blocks: list[TimeBlockRead]
    due_tasks: list[CalendarTaskRead]


class CalendarRangeRead(BaseModel):
    start: date
    end: date
    days: list[CalendarDayRead]
    total_planned_minutes: int


class TimeBlockCreate(BaseModel):
    plan_date: date
    task_id: UUID
    start_at: datetime
    end_at: datetime
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_range(self) -> TimeBlockCreate:
        if self.end_at <= self.start_at:
            raise ValueError("结束时间必须晚于开始时间。")
        return self


class TimeBlockUpdate(BaseModel):
    start_at: datetime | None = None
    end_at: datetime | None = None
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_range(self) -> TimeBlockUpdate:
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("结束时间必须晚于开始时间。")
        return self


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


class InsightRead(BaseModel):
    key: str
    code: str
    severity: Literal["high", "medium", "low"]
    title: str
    reason: str
    suggestion: str
    task_ids: list[UUID] = Field(default_factory=list)
    task_titles: list[str] = Field(default_factory=list)
    project_id: UUID | None = None
    metric: dict[str, object] = Field(default_factory=dict)


class InsightListRead(BaseModel):
    generated_at: datetime
    items: list[InsightRead]
    dismissed_count: int


class InsightDismissRequest(BaseModel):
    key: str = Field(min_length=1, max_length=120)


# ---------------------------------------------------------------------------
# Replanning
# ---------------------------------------------------------------------------


class ReplanRequest(BaseModel):
    plan_date: date | None = None
    reason: str = Field(default="", max_length=300)
    available_minutes: int | None = Field(default=None, ge=5, le=1440)
    keep_task_ids: list[UUID] = Field(default_factory=list)
    unavailable_windows: list[dict[str, str]] = Field(default_factory=list)


class ReplanBlockRead(BaseModel):
    task_id: UUID
    title: str
    priority: TaskPriority
    estimated_minutes: int
    start_at: datetime
    end_at: datetime
    reasons: list[str] = Field(default_factory=list)


class ReplanChangeRead(BaseModel):
    kind: Literal["added", "moved", "removed", "kept"]
    task_id: UUID
    title: str
    before_start: datetime | None = None
    after_start: datetime | None = None


class ReplanDraftRead(BaseModel):
    plan_date: date
    available_minutes: int
    before: list[ReplanBlockRead]
    after: list[ReplanBlockRead]
    changes: list[ReplanChangeRead]
    blocked_tasks: list[BlockedTaskRead]
    unscheduled: list[BlockedTaskRead]
    explanation: list[str]
    plan_token: str


class ReplanApplyRequest(BaseModel):
    plan_date: date
    blocks: list[ReplanBlockRead]
    plan_token: str
    reason: str = Field(default="", max_length=300)


class ReplanApplyResult(BaseModel):
    plan_date: date
    applied: int
    revision_no: int


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


class PreferencesRead(BaseModel):
    timezone: str
    daily_available_minutes: int
    workdays: list[int]
    default_focus_minutes: int
    reminder_prefs: dict[str, object]
    updated_at: datetime


class EnhancedReportRequest(BaseModel):
    report_type: Literal["daily", "weekly", "project"] = "weekly"
    period_start: date
    period_end: date
    project_id: UUID | None = None
    template: Literal["standard", "work"] = "standard"


class PreferencesUpdate(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    daily_available_minutes: int | None = Field(default=None, ge=5, le=1440)
    workdays: list[int] | None = None
    default_focus_minutes: int | None = Field(default=None, ge=5, le=240)
    reminder_prefs: dict[str, object] | None = None

    @field_validator("workdays")
    @classmethod
    def validate_workdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        unique = sorted({int(day) for day in value})
        if not unique or any(day < 0 or day > 6 for day in unique):
            raise ValueError("工作日必须是 0（周一）到 6（周日）之间的数字。")
        return unique
