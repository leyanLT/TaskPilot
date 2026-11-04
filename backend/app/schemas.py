"""Pydantic request and response models for tasks, projects, planning, reports.

The v1.5 models are additive: every v1.0 task field keeps its shape so existing
clients continue to work, while new optional fields carry project, priority,
subtask, plan, notification, and report data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.types import StrictBool

TITLE_MAX = 100
DESCRIPTION_MAX = 500
MIN_ESTIMATE = 5
MAX_ESTIMATE = 1440
MAX_PLAN_ITEMS = 50
MAX_BREAKDOWN_TASKS = 12
MAX_BREAKDOWN_SUBTASKS = 8


class TaskStatus(StrEnum):
    pending = "pending"
    completed = "completed"


class TaskPriority(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class ProjectStatus(StrEnum):
    planning = "planning"
    active = "active"
    completed = "completed"
    archived = "archived"


class NotificationType(StrEnum):
    today_todo = "today_todo"
    due_soon = "due_soon"
    overdue = "overdue"


class ReportType(StrEnum):
    daily = "daily"
    weekly = "weekly"
    project = "project"


class ChatRole(StrEnum):
    user = "user"
    assistant = "assistant"


class ActionType(StrEnum):
    create_task = "create_task"
    create_tasks = "create_tasks"
    complete_task = "complete_task"
    update_task = "update_task"
    delete_task = "delete_task"
    batch_reschedule = "batch_reschedule"
    create_task_breakdown = "create_task_breakdown"
    save_daily_plan = "save_daily_plan"
    save_report = "save_report"
    apply_replan = "apply_replan"
    create_project = "create_project"


class ActionStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    confirmed = "confirmed"
    cancelled = "cancelled"
    expired = "expired"


class ActivityAction(StrEnum):
    task_created = "task_created"
    task_updated = "task_updated"
    task_completed = "task_completed"
    task_reopened = "task_reopened"
    task_deleted = "task_deleted"
    task_project_changed = "task_project_changed"
    subtask_created = "subtask_created"
    project_created = "project_created"
    project_updated = "project_updated"
    project_status_changed = "project_status_changed"


def normalize_due_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("截止时间必须包含时区，例如 2026-11-04T15:00:00+08:00")
    return value.astimezone(UTC)


def normalize_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}必须包含时区，例如 2026-11-04T09:00:00+08:00")
    return value.astimezone(UTC)


def _validate_title(value: str | None) -> str:
    if value is None:
        raise ValueError("标题不能为空")
    value = value.strip()
    if not 1 <= len(value) <= TITLE_MAX:
        raise ValueError(f"标题去除首尾空格后必须为 1-{TITLE_MAX} 个字符")
    return value


def _validate_description(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > DESCRIPTION_MAX:
        raise ValueError(f"描述最多 {DESCRIPTION_MAX} 个字符")
    return value or None


def _validate_optional_text(value: str | None, *, limit: int, label: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{label}最多 {limit} 个字符")
    return value or None


class TaskBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    due_at: datetime | None = None
    project_id: UUID | None = None
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: int | None = Field(default=None, ge=MIN_ESTIMATE, le=MAX_ESTIMATE)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validate_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _validate_description(value)

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, value: datetime | None) -> datetime | None:
        return normalize_due_at(value)


class TaskCreate(TaskBase):
    pass


class SubtaskCreate(BaseModel):
    """Subtask input. The project is always inherited from the parent task."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    due_at: datetime | None = None
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: int | None = Field(default=None, ge=MIN_ESTIMATE, le=MAX_ESTIMATE)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validate_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _validate_description(value)

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, value: datetime | None) -> datetime | None:
        return normalize_due_at(value)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    due_at: datetime | None = None
    status: TaskStatus | None = None
    project_id: UUID | None = None
    priority: TaskPriority | None = None
    estimated_minutes: int | None = Field(default=None, ge=MIN_ESTIMATE, le=MAX_ESTIMATE)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str:
        return _validate_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _validate_description(value)

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, value: datetime | None) -> datetime | None:
        return normalize_due_at(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: TaskStatus | None) -> TaskStatus:
        if value is None:
            raise ValueError("状态不能为空")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> TaskUpdate:
        if not self.model_fields_set:
            raise ValueError("至少提供一个要修改的字段")
        return self


class TaskChanges(BaseModel):
    """Fields the AI is allowed to change through a confirmed update action."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    due_at: datetime | None = None
    priority: TaskPriority | None = None
    estimated_minutes: int | None = Field(default=None, ge=MIN_ESTIMATE, le=MAX_ESTIMATE)
    project_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str:
        return _validate_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _validate_description(value)

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, value: datetime | None) -> datetime | None:
        return normalize_due_at(value)

    @model_validator(mode="after")
    def require_at_least_one_change(self) -> TaskChanges:
        if not self.model_fields_set:
            raise ValueError("至少提供一个要修改的字段")
        return self


class TaskChangesView(BaseModel):
    title: str | None = None
    description: str | None = None
    due_at: datetime | None = None
    priority: TaskPriority | None = None
    estimated_minutes: int | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    changed_fields: list[str] = Field(default_factory=list)

    @field_serializer("due_at")
    def serialize_due_at(self, value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat() if value else None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    status: TaskStatus
    due_at: datetime | None
    project_id: UUID | None = None
    parent_id: UUID | None = None
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: int | None = None
    position: int = 0
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    subtask_count: int = 0
    completed_subtask_count: int = 0

    @field_serializer("due_at", "created_at", "updated_at", "completed_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).isoformat()

    @classmethod
    def from_task(
        cls,
        task: object,
        *,
        subtask_count: int = 0,
        completed_subtask_count: int = 0,
    ) -> TaskRead:
        view = cls.model_validate(task)
        return view.model_copy(
            update={
                "subtask_count": subtask_count,
                "completed_subtask_count": completed_subtask_count,
            }
        )


class TaskDetail(TaskRead):
    subtasks: list[TaskRead] = Field(default_factory=list)
    parent: TaskRead | None = None


class TaskDraft(BaseModel):
    title: str
    description: str | None
    due_at: datetime | None
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: int | None = None
    project_id: UUID | None = None

    @field_serializer("due_at")
    def serialize_due_at(self, value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat() if value else None


class TaskCandidate(BaseModel):
    id: UUID
    title: str
    due_at: datetime | None
    status: TaskStatus

    @field_serializer("due_at")
    def serialize_due_at(self, value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat() if value else None


class SubtaskReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtask_ids: list[UUID] = Field(min_length=1, max_length=100)


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    status: ProjectStatus | None = None
    start_date: date | None = None
    due_date: date | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _validate_description(value)

    @model_validator(mode="after")
    def validate_dates(self) -> ProjectCreate:
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("截止日期不能早于开始日期")
        return self


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    status: ProjectStatus | None = None
    start_date: date | None = None
    due_date: date | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str:
        return _validate_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _validate_description(value)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> ProjectUpdate:
        if not self.model_fields_set:
            raise ValueError("至少提供一个要修改的字段")
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("截止日期不能早于开始日期")
        return self


class ProjectStats(BaseModel):
    total_tasks: int = 0
    completed_tasks: int = 0
    pending_tasks: int = 0
    overdue_tasks: int = 0
    completion_rate: float = 0.0


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    status: ProjectStatus
    start_date: date | None
    due_date: date | None
    created_at: datetime
    updated_at: datetime
    stats: ProjectStats = Field(default_factory=ProjectStats)

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()

    @classmethod
    def from_project(cls, project: object, stats: ProjectStats) -> ProjectRead:
        view = cls.model_validate(project)
        return view.model_copy(update={"stats": stats})


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID | None = None
    task_title: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    action: ActivityAction
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    summary: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class ProjectDetail(BaseModel):
    project: ProjectRead
    tasks: list[TaskRead] = Field(default_factory=list)
    recent_activities: list[ActivityRead] = Field(default_factory=list)


class PlanItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_id: UUID
    start_at: datetime
    end_at: datetime
    note: str | None = Field(default=None, max_length=200)

    @field_validator("start_at")
    @classmethod
    def validate_start(cls, value: datetime) -> datetime:
        return normalize_aware(value, "开始时间")

    @field_validator("end_at")
    @classmethod
    def validate_end(cls, value: datetime) -> datetime:
        return normalize_aware(value, "结束时间")

    @model_validator(mode="after")
    def validate_range(self) -> PlanItemInput:
        if self.end_at <= self.start_at:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class PlanUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_minutes: int = Field(ge=5, le=MAX_ESTIMATE)
    items: list[PlanItemInput] = Field(default_factory=list, max_length=MAX_PLAN_ITEMS)


class PlanItemRead(BaseModel):
    id: UUID
    task_id: UUID
    task_title: str
    task_status: TaskStatus
    priority: TaskPriority
    estimated_minutes: int | None = None
    start_at: datetime
    end_at: datetime
    position: int
    note: str | None = None

    @field_serializer("start_at", "end_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class PlanRead(BaseModel):
    id: UUID
    plan_date: date
    timezone: str
    available_minutes: int
    planned_minutes: int = 0
    items: list[PlanItemRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: NotificationType
    task_id: UUID | None = None
    task_title: str | None = None
    message: str
    due_at: datetime | None = None
    created_at: datetime
    read_at: datetime | None = None

    @field_serializer("due_at", "created_at", "read_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).isoformat()

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class NotificationList(BaseModel):
    items: list[NotificationRead] = Field(default_factory=list)
    unread_count: int = 0


class NotificationReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: StrictBool = True


class CountResponse(BaseModel):
    count: int


class PlanSuggestionItem(BaseModel):
    task_id: UUID
    title: str
    priority: TaskPriority
    estimated_minutes: int
    is_estimate: bool = False
    start_at: datetime
    end_at: datetime
    reasons: list[str] = Field(default_factory=list)

    @field_serializer("start_at", "end_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class PlanSuggestionResponse(BaseModel):
    plan_date: date
    available_minutes: int
    blocks: list[PlanSuggestionItem] = Field(default_factory=list)


class ReportDraft(BaseModel):
    """A generated but not yet saved report."""

    report_type: ReportType
    title: str
    period_start: datetime
    period_end: datetime
    project_id: UUID | None = None
    project_name: str | None = None
    content_md: str
    facts: dict[str, Any] = Field(default_factory=dict)
    ai_used: bool = False

    @field_serializer("period_start", "period_end")
    def serialize_period(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: ReportType
    period_start: datetime | None = None
    period_end: datetime | None = None
    project_id: UUID | None = None

    @field_validator("period_start", "period_end")
    @classmethod
    def validate_period_value(cls, value: datetime | None) -> datetime | None:
        return normalize_aware(value, "统计时间") if value else None

    @model_validator(mode="after")
    def validate_period(self) -> ReportGenerateRequest:
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("开始和结束时间必须同时提供")
        if self.period_start and self.period_end and self.period_end <= self.period_start:
            raise ValueError("结束时间必须晚于开始时间")
        if self.report_type == ReportType.project and self.project_id is None:
            raise ValueError("项目报告必须指定项目")
        return self


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    report_type: ReportType
    title: str = Field(min_length=1, max_length=120)
    period_start: datetime
    period_end: datetime
    project_id: UUID | None = None
    content_md: str = Field(min_length=1, max_length=60_000)
    facts: dict[str, Any] = Field(default_factory=dict)
    ai_used: bool = False

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 120:
            raise ValueError("报告标题必须为 1-120 个字符")
        return value

    @field_validator("period_start", "period_end")
    @classmethod
    def validate_period_value(cls, value: datetime) -> datetime:
        return normalize_aware(value, "统计时间")

    @model_validator(mode="after")
    def validate_period(self) -> ReportCreate:
        if self.period_end <= self.period_start:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class ReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=120)
    content_md: str | None = Field(default=None, min_length=1, max_length=60_000)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> ReportUpdate:
        if not self.model_fields_set:
            raise ValueError("至少提供一个要修改的字段")
        return self


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_type: ReportType
    title: str
    period_start: datetime
    period_end: datetime
    project_id: UUID | None = None
    project_name: str | None = None
    content_md: str
    facts: dict[str, Any] = Field(default_factory=dict)
    ai_used: bool = False
    created_at: datetime
    updated_at: datetime

    @field_serializer("period_start", "period_end", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_type: ReportType
    title: str
    period_start: datetime
    period_end: datetime
    project_id: UUID | None = None
    project_name: str | None = None
    ai_used: bool = False
    created_at: datetime

    @field_serializer("period_start", "period_end", "created_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class PrioritySuggestion(BaseModel):
    task_id: UUID
    title: str
    current_priority: TaskPriority
    suggested_priority: TaskPriority
    score: int
    reasons: list[str] = Field(default_factory=list)
    due_at: datetime | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    estimated_minutes: int | None = None

    @field_serializer("due_at")
    def serialize_due_at(self, value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat() if value else None


class PrioritySuggestionList(BaseModel):
    suggestions: list[PrioritySuggestion] = Field(default_factory=list)


class DashboardCounts(BaseModel):
    total: int = 0
    pending: int = 0
    completed: int = 0
    overdue: int = 0
    due_today: int = 0
    due_soon: int = 0


class DashboardResponse(BaseModel):
    date: date
    timezone: str
    counts: DashboardCounts
    today_tasks: list[TaskRead] = Field(default_factory=list)
    due_soon_tasks: list[TaskRead] = Field(default_factory=list)
    overdue_tasks: list[TaskRead] = Field(default_factory=list)
    projects: list[ProjectRead] = Field(default_factory=list)
    today_plan: PlanRead | None = None
    recent_activities: list[ActivityRead] = Field(default_factory=list)
    unread_notifications: int = 0


class BreakdownSubtaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    priority: TaskPriority = TaskPriority.medium
    estimated_minutes: int | None = Field(default=None, ge=MIN_ESTIMATE, le=MAX_ESTIMATE)
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validate_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _validate_description(value)

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, value: datetime | None) -> datetime | None:
        return normalize_due_at(value)


class BreakdownTaskDraft(BreakdownSubtaskDraft):
    subtasks: list[BreakdownSubtaskDraft] = Field(
        default_factory=list, max_length=MAX_BREAKDOWN_SUBTASKS
    )


class BreakdownDraft(BaseModel):
    """Editable AI task-breakdown proposal. Never written before confirmation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    goal: str = Field(min_length=1, max_length=200)
    project_id: UUID | None = None
    project_name: str | None = None
    tasks: list[BreakdownTaskDraft] = Field(
        default_factory=list, min_length=1, max_length=MAX_BREAKDOWN_TASKS
    )

    @field_validator("goal")
    @classmethod
    def validate_goal(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 200:
            raise ValueError("目标描述必须为 1-200 个字符")
        return value


class PlanDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_id: UUID
    task_title: str | None = None
    start_at: datetime
    end_at: datetime
    note: str | None = Field(default=None, max_length=200)

    @field_validator("start_at", "end_at")
    @classmethod
    def validate_aware(cls, value: datetime) -> datetime:
        return normalize_aware(value, "计划时间")

    @model_validator(mode="after")
    def validate_range(self) -> PlanDraftItem:
        if self.end_at <= self.start_at:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class PlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_date: date
    available_minutes: int = Field(ge=5, le=MAX_ESTIMATE)
    items: list[PlanDraftItem] = Field(default_factory=list, max_length=MAX_PLAN_ITEMS)


class ReportDraftPayload(BaseModel):
    """Report content embedded in a pending action before confirmation."""

    model_config = ConfigDict(extra="forbid")

    report: ReportCreate


class PendingActionView(BaseModel):
    id: UUID
    action_type: ActionType
    status: ActionStatus
    summary: str
    proposed_task: TaskDraft | None = None
    proposed_tasks: list[TaskDraft] = Field(default_factory=list)
    target_task: TaskRead | None = None
    target_tasks: list[TaskRead] = Field(default_factory=list)
    changes: TaskChangesView | None = None
    proposed_breakdown: BreakdownDraft | None = None
    proposed_plan: PlanDraft | None = None
    proposed_report: ReportDraft | None = None
    proposed_replan: dict[str, Any] | None = None
    proposed_project: dict[str, Any] | None = None
    created_at: datetime
    expires_at: datetime

    @field_serializer("created_at", "expires_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class ChatMessageView(BaseModel):
    id: UUID
    role: ChatRole
    content: str
    action: PendingActionView | None = None
    candidates: list[TaskCandidate] = Field(default_factory=list)
    prompt_version: str | None = None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat()


class AssistantHistoryResponse(BaseModel):
    messages: list[ChatMessageView]


class AssistantTurnResponse(BaseModel):
    user_message: ChatMessageView
    assistant_message: ChatMessageView


class AssistantMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=2000)
    selected_task_id: UUID | None = None
    source_message_id: UUID | None = None


class ConfirmActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: UUID
    confirm: StrictBool
    payload_overrides: dict[str, Any] | None = None


class ConfirmActionResponse(BaseModel):
    action_id: UUID
    status: ActionStatus
    message: str
    task: TaskRead | None = None
    affected_tasks: list[TaskRead] = Field(default_factory=list)
    report_id: UUID | None = None
    plan_date: date | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    agent_configured: bool


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
