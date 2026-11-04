"""Server-side pending operations for AI-assisted task changes.

Every AI write becomes a persisted ``PendingAction`` first. Confirmation claims
the row atomically, executes through services inside one transaction, and stores
the result so retries stay idempotent. v1.5 adds task-breakdown, daily-plan, and
report drafts, all of which can be edited before confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import (
    DatabaseOperationError,
    PendingActionConflictError,
    PendingActionExpiredError,
    PendingActionNotFoundError,
    TaskAlreadyCompletedError,
    TaskHasUnfinishedSubtasksError,
    TaskNotFoundError,
)
from app.models import PendingAction, Task
from app.repositories.pending_action_repository import PendingActionRepository
from app.schemas import (
    ActionStatus,
    ActionType,
    BreakdownDraft,
    ConfirmActionResponse,
    PendingActionView,
    PlanDraft,
    PlanItemInput,
    PlanUpsert,
    ProjectCreate,
    ReportCreate,
    ReportDraft,
    SubtaskCreate,
    TaskChanges,
    TaskChangesView,
    TaskCreate,
    TaskDraft,
    TaskRead,
    TaskStatus,
    TaskUpdate,
)
from app.schemas_v2 import ReplanDraftRead
from app.services.planning_service import PlanningService
from app.services.project_service import ProjectService
from app.services.replan_service import ReplanService
from app.services.report_service import ReportService
from app.services.task_service import TaskService

MAX_BATCH_CREATE = 5
MAX_BATCH_RESCHEDULE = 20


@dataclass(frozen=True)
class ActionExecution:
    message: str
    task: Task | None = None
    affected_tasks: list[Task] = field(default_factory=list)
    report_id: str | None = None
    plan_date: date | None = None


class PendingActionService:
    """Create, inspect, confirm, cancel, and expire pending AI operations.

    ``confirm`` claims the action atomically before writing data and stores the
    confirmed result in the same transaction, which makes retries idempotent.
    Every action type must execute through services inside this transaction.
    """

    def __init__(
        self,
        session: Session,
        task_service: TaskService,
        *,
        ttl_minutes: int = 30,
        timezone: ZoneInfo | None = None,
    ) -> None:
        self.session = session
        self.task_service = task_service
        self.timezone = timezone or ZoneInfo("UTC")
        self.repository = PendingActionRepository(session)
        self.ttl = timedelta(minutes=ttl_minutes)

    def _rollback(self) -> None:
        try:
            self.session.rollback()
        except SQLAlchemyError:
            pass

    def _commit(self) -> None:
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

    def _new_action(
        self,
        *,
        action_type: ActionType,
        payload: dict[str, object],
        summary: str,
    ) -> PendingAction:
        now = utc_now()
        action = PendingAction(
            action_type=action_type.value,
            status=ActionStatus.pending.value,
            payload=payload,
            summary=summary,
            created_at=now,
            expires_at=now + self.ttl,
        )
        try:
            self.repository.add(action)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        self._commit()
        return action

    # ------------------------------------------------------------------
    # Draft creation
    # ------------------------------------------------------------------

    def create_task_draft(self, data: TaskCreate) -> PendingAction:
        payload = data.model_dump(mode="json")
        return self._new_action(
            action_type=ActionType.create_task,
            payload=payload,
            summary=f"创建任务「{data.title}」",
        )

    def create_tasks_drafts(
        self,
        drafts: list[TaskCreate],
        *,
        summary: str | None = None,
    ) -> PendingAction:
        if not drafts:
            raise PendingActionConflictError("至少需要一个任务草稿。")
        if len(drafts) > MAX_BATCH_CREATE:
            raise PendingActionConflictError(f"一次最多创建 {MAX_BATCH_CREATE} 个任务草稿。")
        return self._new_action(
            action_type=ActionType.create_tasks,
            payload={"tasks": [draft.model_dump(mode="json") for draft in drafts]},
            summary=summary or f"创建 {len(drafts)} 个任务草稿",
        )

    def create_breakdown_draft(
        self,
        breakdown: BreakdownDraft,
        *,
        summary: str | None = None,
    ) -> PendingAction:
        total = sum(1 + len(item.subtasks) for item in breakdown.tasks)
        return self._new_action(
            action_type=ActionType.create_task_breakdown,
            payload={"breakdown": breakdown.model_dump(mode="json")},
            summary=summary
            or f"拆解「{breakdown.goal}」为 {len(breakdown.tasks)} 组任务（共 {total} 项）",
        )

    def create_daily_plan_draft(self, plan: PlanDraft) -> PendingAction:
        total = int(sum((item.end_at - item.start_at).total_seconds() // 60 for item in plan.items))
        return self._new_action(
            action_type=ActionType.save_daily_plan,
            payload={"plan": plan.model_dump(mode="json")},
            summary=(
                f"保存 {plan.plan_date.isoformat()} 的今日计划"
                f"（{len(plan.items)} 个时间块，共 {total} 分钟）"
            ),
        )

    def create_report_draft(
        self,
        draft: ReportDraft,
        *,
        summary: str | None = None,
    ) -> PendingAction:
        return self._new_action(
            action_type=ActionType.save_report,
            payload={"report": draft.model_dump(mode="json")},
            summary=summary or f"保存报告「{draft.title}」",
        )

    def create_project_draft(self, data: ProjectCreate) -> PendingAction:
        return self._new_action(
            action_type=ActionType.create_project,
            payload={"project": data.model_dump(mode="json")},
            summary=f"创建项目「{data.name}」",
        )

    def create_completion_draft(self, task: Task) -> PendingAction:
        if task.status == TaskStatus.completed.value:
            raise TaskAlreadyCompletedError()
        unfinished = self.task_service.unfinished_subtask_count(task.id)
        if unfinished:
            raise TaskHasUnfinishedSubtasksError(details={"unfinished_subtasks": unfinished})
        return self._new_action(
            action_type=ActionType.complete_task,
            payload={"task_id": task.id},
            summary=f"将任务「{task.title}」标记为已完成",
        )

    def create_update_draft(
        self,
        task: Task,
        changes: TaskChanges,
        *,
        summary: str | None = None,
    ) -> PendingAction:
        fields = changes.model_dump(mode="json", exclude_unset=True)
        if fields.get("status") == TaskStatus.completed.value:
            unfinished = self.task_service.unfinished_subtask_count(task.id)
            if unfinished:
                raise TaskHasUnfinishedSubtasksError(details={"unfinished_subtasks": unfinished})
        return self._new_action(
            action_type=ActionType.update_task,
            payload={"task_id": task.id, "changes": fields},
            summary=summary or f"修改任务「{task.title}」",
        )

    def create_delete_draft(self, task: Task) -> PendingAction:
        subtask_count = self.task_service.subtask_count(task.id)
        summary = f"删除任务「{task.title}」"
        if subtask_count:
            summary += f"，同时删除 {subtask_count} 个子任务（不可恢复）"
        return self._new_action(
            action_type=ActionType.delete_task,
            payload={"task_id": task.id, "subtask_count": subtask_count},
            summary=summary,
        )

    def create_replan_draft(
        self,
        draft: ReplanDraftRead,
        *,
        summary: str | None = None,
    ) -> PendingAction:
        total_minutes = sum(block.estimated_minutes for block in draft.after)
        return self._new_action(
            action_type=ActionType.apply_replan,
            payload={"replan": draft.model_dump(mode="json")},
            summary=summary
            or (
                f"重排 {draft.plan_date.isoformat()} 的计划"
                f"（{len(draft.after)} 个时间块，共 {total_minutes} 分钟）"
            ),
        )

    def create_batch_reschedule_draft(
        self,
        tasks: list[Task],
        due_at: datetime,
        *,
        summary: str | None = None,
    ) -> PendingAction:
        if not tasks:
            raise PendingActionConflictError("没有可调整的任务。")
        if len(tasks) > MAX_BATCH_RESCHEDULE:
            raise PendingActionConflictError(
                f"一次最多调整 {MAX_BATCH_RESCHEDULE} 个任务，请缩小范围。"
            )
        if any(task.status != TaskStatus.pending.value for task in tasks):
            raise PendingActionConflictError("只能批量调整待完成任务的截止时间。")
        return self._new_action(
            action_type=ActionType.batch_reschedule,
            payload={
                "task_ids": [task.id for task in tasks],
                "due_at": due_at.isoformat(),
            },
            summary=summary or f"调整 {len(tasks)} 个任务的截止时间",
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_action(self, action_id: str | UUID) -> PendingAction:
        try:
            action = self.repository.get(str(action_id))
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        if action is None:
            raise PendingActionNotFoundError()
        return action

    def expire_if_needed(self, action: PendingAction) -> PendingAction:
        if action.status != ActionStatus.pending.value or action.expires_at > utc_now():
            return action
        now = utc_now()
        try:
            changed = self.repository.mark_expired(action.id, now=now)
            if changed:
                self._commit()
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        action.status = ActionStatus.expired.value
        action.resolved_at = now
        return action

    def _project_name(self, project_id: object) -> str | None:
        from app.repositories.project_repository import ProjectRepository

        project = ProjectRepository(self.session).get(str(project_id))
        return project.name if project else None

    def _task_title(self, task_id: str) -> str | None:
        task = self.task_service.get_task_or_none(task_id)
        return task.title if task else None

    def _task_view(self, task: Task) -> TaskRead:
        total, completed = self.task_service.subtask_counts(task.id)
        return TaskRead.from_task(task, subtask_count=total, completed_subtask_count=completed)

    def to_view(self, action: PendingAction) -> PendingActionView:
        proposed: TaskDraft | None = None
        proposed_tasks: list[TaskDraft] = []
        target_task: TaskRead | None = None
        target_tasks: list[TaskRead] = []
        changes_view: TaskChangesView | None = None
        proposed_breakdown: BreakdownDraft | None = None
        proposed_plan: PlanDraft | None = None
        proposed_report: ReportDraft | None = None
        proposed_replan_view: dict[str, object] | None = None
        proposed_project: dict[str, object] | None = None

        if action.action_type == ActionType.create_task.value:
            try:
                proposed = TaskDraft.model_validate(action.payload)
            except ValidationError as exc:
                raise PendingActionConflictError("待确认操作的数据无效。") from exc
        elif action.action_type == ActionType.create_tasks.value:
            raw_tasks = action.payload.get("tasks")
            if not isinstance(raw_tasks, list) or not raw_tasks:
                raise PendingActionConflictError("待确认操作的数据无效。")
            try:
                proposed_tasks = [TaskDraft.model_validate(item) for item in raw_tasks]
            except ValidationError as exc:
                raise PendingActionConflictError("待确认操作的数据无效。") from exc
        elif action.action_type == ActionType.create_task_breakdown.value:
            payload = action.payload.get("breakdown")
            if not isinstance(payload, dict):
                raise PendingActionConflictError("待确认操作的数据无效。")
            try:
                proposed_breakdown = BreakdownDraft.model_validate(payload)
            except ValidationError as exc:
                raise PendingActionConflictError("待确认操作的数据无效。") from exc
            if proposed_breakdown.project_id and not proposed_breakdown.project_name:
                proposed_breakdown = proposed_breakdown.model_copy(
                    update={"project_name": self._project_name(proposed_breakdown.project_id)}
                )
        elif action.action_type == ActionType.save_daily_plan.value:
            payload = action.payload.get("plan")
            if not isinstance(payload, dict):
                raise PendingActionConflictError("待确认操作的数据无效。")
            try:
                proposed_plan = PlanDraft.model_validate(payload)
            except ValidationError as exc:
                raise PendingActionConflictError("待确认操作的数据无效。") from exc
            proposed_plan = proposed_plan.model_copy(
                update={
                    "items": [
                        item.model_copy(update={"task_title": self._task_title(str(item.task_id))})
                        for item in proposed_plan.items
                    ]
                }
            )
        elif action.action_type == ActionType.save_report.value:
            payload = action.payload.get("report")
            if not isinstance(payload, dict):
                raise PendingActionConflictError("待确认操作的数据无效。")
            try:
                proposed_report = ReportDraft.model_validate(payload)
            except ValidationError as exc:
                raise PendingActionConflictError("待确认操作的数据无效。") from exc
        elif action.action_type in {
            ActionType.complete_task.value,
            ActionType.update_task.value,
            ActionType.delete_task.value,
        }:
            task_id = str(action.payload.get("task_id", ""))
            task = self.task_service.get_task_or_none(task_id)
            if task is not None:
                target_task = self._task_view(task)
            if action.action_type == ActionType.update_task.value:
                raw_changes = action.payload.get("changes")
                if not isinstance(raw_changes, dict):
                    raise PendingActionConflictError("待确认操作的数据无效。")
                try:
                    changes = TaskChanges.model_validate(raw_changes)
                except ValidationError as exc:
                    raise PendingActionConflictError("待确认操作的数据无效。") from exc
                changes_view = TaskChangesView(
                    title=changes.title,
                    description=changes.description,
                    due_at=changes.due_at,
                    priority=changes.priority,
                    estimated_minutes=changes.estimated_minutes,
                    project_id=changes.project_id,
                    project_name=(
                        self._project_name(changes.project_id) if changes.project_id else None
                    ),
                    changed_fields=sorted(changes.model_fields_set),
                )
        elif action.action_type == ActionType.apply_replan.value:
            payload = action.payload.get("replan")
            if not isinstance(payload, dict):
                raise PendingActionConflictError("待确认操作的数据无效。")
            try:
                proposed_replan = ReplanDraftRead.model_validate(payload)
            except ValidationError as exc:
                raise PendingActionConflictError("待确认操作的数据无效。") from exc
            proposed_replan_view = proposed_replan.model_dump(mode="json")
        elif action.action_type == ActionType.batch_reschedule.value:
            raw_ids = action.payload.get("task_ids")
            if not isinstance(raw_ids, list):
                raise PendingActionConflictError("待确认操作的数据无效。")
            for task_id in raw_ids:
                task = self.task_service.get_task_or_none(str(task_id))
                if task is not None:
                    target_tasks.append(self._task_view(task))

        return PendingActionView(
            id=UUID(action.id),
            action_type=ActionType(action.action_type),
            status=ActionStatus(action.status),
            summary=action.summary,
            proposed_task=proposed,
            proposed_tasks=proposed_tasks,
            target_task=target_task,
            target_tasks=target_tasks,
            changes=changes_view,
            proposed_breakdown=proposed_breakdown,
            proposed_plan=proposed_plan,
            proposed_report=proposed_report,
            proposed_replan=proposed_replan_view,
            proposed_project=proposed_project,
            created_at=action.created_at,
            expires_at=action.expires_at,
        )

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    def _result_for_confirmed(self, action: PendingAction) -> ConfirmActionResponse:
        message = "操作已确认并执行。"
        task: Task | None = None
        affected_tasks: list[Task] = []
        report_id: UUID | None = None
        plan_date: date | None = None

        if action.action_type == ActionType.create_project.value:
            project_payload = action.payload.get("project")
            project_name = (
                project_payload.get("name") if isinstance(project_payload, dict) else None
            )
            message = f"项目「{project_name}」已创建。" if project_name else "项目已创建。"

        if action.action_type == ActionType.apply_replan.value:
            payload = action.payload.get("replan")
            if isinstance(payload, dict) and payload.get("plan_date"):
                try:
                    plan_date = date.fromisoformat(str(payload["plan_date"]))
                except ValueError:
                    plan_date = None
            message = "重排方案已写入计划，原计划已记入修订历史。"

        if action.action_type == ActionType.delete_task.value:
            message = "删除操作已执行，任务已删除。"
        elif action.action_type == ActionType.create_tasks.value:
            message = "批量创建操作已执行。"
        elif action.action_type == ActionType.create_task_breakdown.value:
            created_ids = action.payload.get("_created_task_ids")
            if isinstance(created_ids, list):
                for task_id in created_ids:
                    found = self.task_service.get_task_or_none(str(task_id))
                    if found is not None:
                        affected_tasks.append(found)
            message = f"任务拆解已创建，共 {len(affected_tasks)} 项；重复确认不会再次创建。"
        elif action.action_type == ActionType.save_daily_plan.value:
            plan_payload = action.payload.get("plan")
            if isinstance(plan_payload, dict) and plan_payload.get("plan_date"):
                try:
                    plan_date = date.fromisoformat(str(plan_payload["plan_date"]))
                except ValueError:
                    plan_date = None
            message = "今日计划已保存。"
        elif action.action_type == ActionType.save_report.value:
            report_ref = action.payload.get("_report_id") or action.result_task_id
            if report_ref:
                try:
                    report_id = UUID(str(report_ref))
                except ValueError:
                    report_id = None
            message = "报告已保存。"
        elif action.action_type == ActionType.batch_reschedule.value:
            raw_ids = action.payload.get("task_ids")
            if isinstance(raw_ids, list):
                for task_id in raw_ids:
                    found = self.task_service.get_task_or_none(str(task_id))
                    if found is not None:
                        affected_tasks.append(found)
            message = f"已调整 {len(affected_tasks)} 个任务的截止时间。"
        elif action.action_type == ActionType.create_task.value and action.result_task_id:
            task = self.task_service.get_task_or_none(action.result_task_id)
            message = "操作已确认并执行。" if task else "操作已确认并执行。关联任务已不存在。"
        elif action.result_task_id:
            task = self.task_service.get_task_or_none(action.result_task_id)
            message = "操作已确认并执行。" if task else "操作已确认并执行。关联任务已不存在。"

        return ConfirmActionResponse(
            action_id=UUID(action.id),
            status=ActionStatus.confirmed,
            message=message,
            task=TaskRead.model_validate(task) if task else None,
            affected_tasks=[TaskRead.model_validate(item) for item in affected_tasks],
            report_id=report_id,
            plan_date=plan_date,
        )

    def _handle_claim_failure(self, action_id: str, *, confirm: bool) -> ConfirmActionResponse:
        action = self.get_action(action_id)
        status = action.status
        if status == ActionStatus.confirmed.value:
            if not confirm:
                raise PendingActionConflictError("该操作已经执行，无法取消。")
            return self._result_for_confirmed(action)
        if status == ActionStatus.cancelled.value:
            if confirm:
                raise PendingActionConflictError("该操作已取消，无法再次确认。")
            return ConfirmActionResponse(
                action_id=UUID(action.id),
                status=ActionStatus.cancelled,
                message="操作已取消。",
            )
        if status == ActionStatus.expired.value:
            raise PendingActionExpiredError()
        if status == ActionStatus.pending.value:
            # The only reason a pending claim fails is expiry.
            try:
                self.repository.mark_expired(action.id, now=utc_now())
                self._commit()
            except SQLAlchemyError:
                self._rollback()
            raise PendingActionExpiredError()
        raise PendingActionConflictError()

    def confirm(
        self,
        action_id: str | UUID,
        *,
        confirm: bool,
        payload_overrides: dict[str, object] | None = None,
    ) -> ConfirmActionResponse:
        action_key = str(action_id)
        now = utc_now()

        if not confirm:
            try:
                claimed = self.repository.claim_for_cancellation(action_key)
            except SQLAlchemyError as exc:
                self._rollback()
                raise DatabaseOperationError() from exc
            if not claimed:
                return self._handle_claim_failure(action_key, confirm=False)
            self._commit()
            return ConfirmActionResponse(
                action_id=UUID(action_key),
                status=ActionStatus.cancelled,
                message="操作已取消，未修改任何任务。",
            )

        try:
            claimed = self.repository.claim_for_confirmation(action_key, now)
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc

        if not claimed:
            return self._handle_claim_failure(action_key, confirm=True)

        try:
            action = self.get_action(action_key)
            if payload_overrides is not None:
                self._apply_overrides(action, payload_overrides)
            execution = self._execute(action)
            primary_task = execution.task
            result_ref = primary_task.id if primary_task else execution.report_id
            if execution.plan_date is not None:
                result_ref = None
            self._remember_result(action, execution)
            if not self.repository.mark_confirmed(
                action.id,
                result_task_id=result_ref,
                now=utc_now(),
            ):
                raise PendingActionConflictError("待确认操作状态异常，请刷新后重试。")
            self._commit()
        except ValidationError as exc:
            self._rollback()
            details = [
                {
                    "field": ".".join(str(part) for part in error.get("loc", ())),
                    "message": error.get("msg", "输入无效"),
                }
                for error in exc.errors()
            ]
            raise PendingActionConflictError(
                "提交的修改内容无效，请检查后重试。", details=details
            ) from exc
        except (TaskNotFoundError, TaskAlreadyCompletedError, PendingActionConflictError):
            self._rollback()
            raise
        except SQLAlchemyError as exc:
            self._rollback()
            raise DatabaseOperationError() from exc
        except Exception:
            self._rollback()
            raise

        return ConfirmActionResponse(
            action_id=UUID(action_key),
            status=ActionStatus.confirmed,
            message=execution.message,
            task=TaskRead.model_validate(primary_task) if primary_task else None,
            affected_tasks=[TaskRead.model_validate(item) for item in execution.affected_tasks],
            report_id=UUID(execution.report_id) if execution.report_id else None,
            plan_date=execution.plan_date,
        )

    def _apply_overrides(self, action: PendingAction, overrides: dict[str, object]) -> None:
        if action.action_type == ActionType.create_task_breakdown.value:
            breakdown = BreakdownDraft.model_validate(overrides)
            action.payload = {"breakdown": breakdown.model_dump(mode="json")}
            total = sum(1 + len(item.subtasks) for item in breakdown.tasks)
            action.summary = (
                f"拆解「{breakdown.goal}」为 {len(breakdown.tasks)} 组任务（共 {total} 项）"
            )[:300]
            return
        if action.action_type == ActionType.save_daily_plan.value:
            plan = PlanDraft.model_validate(overrides)
            action.payload = {"plan": plan.model_dump(mode="json")}
            return
        if action.action_type == ActionType.save_report.value:
            raw = overrides.get("report") if "report" in overrides else overrides
            report = _report_create(raw)
            action.payload = {"report": report.model_dump(mode="json")}
            action.summary = f"保存报告「{report.title}」"[:300]
            return
        raise PendingActionConflictError("该操作不支持修改内容后确认。")

    def _remember_result(self, action: PendingAction, execution: ActionExecution) -> None:
        if action.action_type == ActionType.create_task_breakdown.value:
            payload = dict(action.payload)
            payload["_created_task_ids"] = [task.id for task in execution.affected_tasks]
            action.payload = payload
        elif action.action_type == ActionType.save_report.value and execution.report_id:
            payload = dict(action.payload)
            payload["_report_id"] = execution.report_id
            action.payload = payload

    def _execute(self, action: PendingAction) -> ActionExecution:
        if action.action_type == ActionType.create_task.value:
            try:
                data = TaskCreate.model_validate(action.payload)
            except ValidationError as exc:
                raise PendingActionConflictError("待确认的创建任务数据无效。") from exc
            task = self.task_service.create_task(data, commit=False)
            return ActionExecution(message="任务已创建。", task=task)

        if action.action_type == ActionType.create_tasks.value:
            raw_tasks = action.payload.get("tasks")
            if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= MAX_BATCH_CREATE:
                raise PendingActionConflictError("待确认的批量创建数据无效。")
            try:
                drafts = [TaskCreate.model_validate(item) for item in raw_tasks]
            except ValidationError as exc:
                raise PendingActionConflictError("待确认的批量创建数据无效。") from exc
            created = [self.task_service.create_task(draft, commit=False) for draft in drafts]
            return ActionExecution(
                message=f"已创建 {len(created)} 个任务。",
                affected_tasks=created,
            )

        if action.action_type == ActionType.create_task_breakdown.value:
            try:
                breakdown = BreakdownDraft.model_validate(action.payload.get("breakdown"))
            except ValidationError as exc:
                raise PendingActionConflictError("待确认的任务拆解数据无效。") from exc
            created_tasks: list[Task] = []
            for item in breakdown.tasks:
                parent = self.task_service.create_task(
                    TaskCreate(
                        title=item.title,
                        description=item.description,
                        due_at=item.due_at,
                        project_id=breakdown.project_id,
                        priority=item.priority,
                        estimated_minutes=item.estimated_minutes,
                    ),
                    commit=False,
                )
                created_tasks.append(parent)
                for subtask in item.subtasks:
                    child = self.task_service.create_subtask(
                        parent.id,
                        SubtaskCreate(
                            title=subtask.title,
                            description=subtask.description,
                            due_at=subtask.due_at,
                            priority=subtask.priority,
                            estimated_minutes=subtask.estimated_minutes,
                        ),
                        commit=False,
                    )
                    created_tasks.append(child)
            return ActionExecution(
                message=f"任务拆解已创建，共 {len(created_tasks)} 项任务。",
                affected_tasks=created_tasks,
            )

        if action.action_type == ActionType.save_daily_plan.value:
            try:
                plan = PlanDraft.model_validate(action.payload.get("plan"))
            except ValidationError as exc:
                raise PendingActionConflictError("待确认的今日计划数据无效。") from exc
            planning = PlanningService(self.session, timezone=self.timezone)
            planning.save_plan(
                plan.plan_date,
                PlanUpsert(
                    available_minutes=plan.available_minutes,
                    items=[
                        PlanItemInput(
                            task_id=item.task_id,
                            start_at=item.start_at,
                            end_at=item.end_at,
                            note=item.note,
                        )
                        for item in plan.items
                    ],
                ),
                commit=False,
            )
            tasks = [self.task_service.get_task(str(item.task_id)) for item in plan.items]
            return ActionExecution(
                message=f"已保存 {plan.plan_date.isoformat()} 的今日计划。",
                affected_tasks=tasks,
                plan_date=plan.plan_date,
            )

        if action.action_type == ActionType.save_report.value:
            try:
                report_data = _report_create(action.payload.get("report"))
            except ValidationError as exc:
                raise PendingActionConflictError("待确认的报告数据无效。") from exc
            reports = ReportService(self.session, timezone=self.timezone)
            report = reports.save(report_data, commit=False)
            return ActionExecution(
                message=f"报告「{report.title}」已保存。",
                report_id=report.id,
            )

        if action.action_type == ActionType.create_project.value:
            raw_project = action.payload.get("project")
            if not isinstance(raw_project, dict):
                raise PendingActionConflictError("待确认的项目数据无效。")
            try:
                project_data = ProjectCreate.model_validate(raw_project)
            except ValidationError as exc:
                raise PendingActionConflictError("待确认的项目数据无效。") from exc
            project = ProjectService(self.session, timezone=self.timezone).create_project(
                project_data, commit=False
            )
            return ActionExecution(message=f"项目「{project.name}」已创建。")

        if action.action_type == ActionType.apply_replan.value:
            raw_replan = action.payload.get("replan")
            if not isinstance(raw_replan, dict):
                raise PendingActionConflictError("待确认的重排方案数据无效。")
            try:
                draft = ReplanDraftRead.model_validate(raw_replan)
            except ValidationError as exc:
                raise PendingActionConflictError("待确认的重排方案数据无效。") from exc
            replan_service = ReplanService(self.session, timezone=self.timezone)
            replan_service.apply(
                plan_date=draft.plan_date,
                blocks=draft.after,
                plan_token=draft.plan_token,
                reason="AI 重排方案经用户确认",
                source="agent",
                action_id=action.id,
                commit=False,
            )
            tasks = [self.task_service.get_task(str(block.task_id)) for block in draft.after]
            return ActionExecution(
                message=f"已写入 {draft.plan_date.isoformat()} 的重排计划。",
                affected_tasks=tasks,
                plan_date=draft.plan_date,
            )

        if action.action_type == ActionType.complete_task.value:
            task_id = str(action.payload.get("task_id", ""))
            if not task_id:
                raise PendingActionConflictError("待确认的完成任务数据无效。")
            task = self.task_service.get_task(task_id)
            if task.status == TaskStatus.completed.value:
                return ActionExecution(message="任务已经是完成状态。", task=task)
            completed = self.task_service.set_status(task.id, TaskStatus.completed, commit=False)
            return ActionExecution(message="任务已完成。", task=completed)

        if action.action_type == ActionType.update_task.value:
            task_id = str(action.payload.get("task_id", ""))
            raw_changes = action.payload.get("changes")
            if not task_id or not isinstance(raw_changes, dict):
                raise PendingActionConflictError("待确认的修改任务数据无效。")
            try:
                changes = TaskChanges.model_validate(raw_changes)
                update = TaskUpdate.model_validate(changes.model_dump(exclude_unset=True))
            except ValidationError as exc:
                raise PendingActionConflictError("待确认的修改任务数据无效。") from exc
            task = self.task_service.update_task(task_id, update, commit=False)
            return ActionExecution(message="任务已更新。", task=task)

        if action.action_type == ActionType.delete_task.value:
            task_id = str(action.payload.get("task_id", ""))
            if not task_id:
                raise PendingActionConflictError("待确认的删除任务数据无效。")
            task = self.task_service.get_task(task_id)
            subtask_count = int(action.payload.get("subtask_count", 0) or 0)
            self.task_service.delete_task(
                task.id, confirm_subtasks=bool(subtask_count), commit=False
            )
            return ActionExecution(
                message=f"任务「{task.title}」已删除。",
                affected_tasks=[task],
            )

        if action.action_type == ActionType.batch_reschedule.value:
            raw_ids = action.payload.get("task_ids")
            try:
                due_at = datetime.fromisoformat(str(action.payload.get("due_at", "")))
            except ValueError as exc:
                raise PendingActionConflictError("待确认的批量改期数据无效。") from exc
            if due_at.tzinfo is None or not isinstance(raw_ids, list) or not raw_ids:
                raise PendingActionConflictError("待确认的批量改期数据无效。")
            if len(raw_ids) > MAX_BATCH_RESCHEDULE:
                raise PendingActionConflictError("批量改期数量超出限制。")
            tasks: list[Task] = []
            for task_id in raw_ids:
                task = self.task_service.get_task(str(task_id))
                if task.status != TaskStatus.pending.value:
                    raise PendingActionConflictError("只能批量调整待完成任务的截止时间。")
                tasks.append(task)
            updated = [
                self.task_service.update_task(
                    task.id,
                    TaskUpdate(due_at=due_at),
                    commit=False,
                )
                for task in tasks
            ]
            return ActionExecution(
                message=f"已调整 {len(updated)} 个任务的截止时间。",
                affected_tasks=updated,
            )

        raise PendingActionConflictError("不支持的待确认操作类型。")


def _report_create(payload: object) -> ReportCreate:
    """Build a save request from an action payload, ignoring preview-only fields."""

    if not isinstance(payload, dict):
        raise PendingActionConflictError("待确认的报告数据无效。")
    allowed = (
        "report_type",
        "title",
        "period_start",
        "period_end",
        "project_id",
        "content_md",
        "facts",
        "ai_used",
    )
    return ReportCreate.model_validate({key: payload[key] for key in allowed if key in payload})
