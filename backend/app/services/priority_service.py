"""Deterministic priority scoring and AI-ready explanations.

The LLM may narrate these results, but the score and the reasons are computed
from real task and project rows so a suggestion can never be hallucinated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import DatabaseOperationError
from app.models import Project, Task
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.schemas import PrioritySuggestion, TaskPriority, TaskStatus

PRIORITY_LABELS = {"high": "高", "medium": "中", "low": "弱"}
BASE_SCORE = {"high": 30, "medium": 15, "low": 5}
PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class PriorityAssessment:
    score: int
    suggested_priority: TaskPriority
    reasons: list[str] = field(default_factory=list)


class PriorityService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.task_repository = TaskRepository(session)
        self.project_repository = ProjectRepository(session)

    @staticmethod
    def _suggested(score: int) -> TaskPriority:
        if score >= 60:
            return TaskPriority.high
        if score >= 35:
            return TaskPriority.medium
        return TaskPriority.low

    def assess(
        self,
        task: Task,
        project: Project | None = None,
        *,
        now: datetime | None = None,
    ) -> PriorityAssessment:
        now = now or utc_now()
        if task.status == TaskStatus.completed.value:
            return PriorityAssessment(
                score=0,
                suggested_priority=TaskPriority(task.priority),
                reasons=["任务已完成，不再参与优先级建议"],
            )

        score = BASE_SCORE.get(task.priority, 15)
        reasons = [f"用户设置的优先级为{PRIORITY_LABELS.get(task.priority, task.priority)}"]

        if task.due_at is not None:
            hours_left = (task.due_at - now).total_seconds() / 3600
            if hours_left < 0:
                score += 50
                reasons.append("任务已逾期")
            elif hours_left <= 24:
                score += 35
                reasons.append("24 小时内到期")
            elif hours_left <= 72:
                score += 20
                reasons.append("3 天内到期")
            elif hours_left <= 168:
                score += 10
                reasons.append("7 天内到期")
            else:
                reasons.append("截止时间较宽松")
        else:
            reasons.append("未设置截止时间")

        if task.estimated_minutes is not None:
            if task.estimated_minutes <= 30:
                score += 6
                reasons.append(f"预计耗时较短（{task.estimated_minutes} 分钟）")
            elif task.estimated_minutes >= 180:
                score -= 4
                reasons.append(f"预计耗时较长（{task.estimated_minutes} 分钟）")

        if project is None and task.project_id:
            project = self.project_repository.get(task.project_id)
        if project is None:
            reasons.append("未归属项目")
        else:
            today = now.astimezone(self.timezone).date()
            if project.status == "archived":
                score -= 20
                reasons.append(f"所属项目「{project.name}」已归档")
            elif project.status == "completed":
                score -= 15
                reasons.append(f"所属项目「{project.name}」已完成")
            else:
                if project.due_date is not None:
                    days_left = (project.due_date - today).days
                    if days_left < 0:
                        score += 12
                        reasons.append(f"所属项目「{project.name}」已过截止日期")
                    elif days_left <= 3:
                        score += 10
                        reasons.append(f"所属项目「{project.name}」将在 {days_left} 天内到期")
                if project.status == "active":
                    score += 4
                    reasons.append(f"所属项目「{project.name}」进行中")

        score = max(0, min(100, score))
        return PriorityAssessment(
            score=score,
            suggested_priority=self._suggested(score),
            reasons=reasons,
        )

    def suggestions(
        self,
        *,
        limit: int = 10,
        project_id: str | UUID | None = None,
        now: datetime | None = None,
    ) -> list[PrioritySuggestion]:
        now = now or utc_now()
        try:
            rows = self.task_repository.list_with_counts(
                status=TaskStatus.pending.value,
                project_id=str(project_id) if project_id else None,
                sort_by="due_at",
                order="asc",
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc

        projects: dict[str, Project] = {}
        for task, total_subtasks, _ in rows:
            if total_subtasks:
                continue  # container task: its subtasks are the actionable work
            if task.project_id and task.project_id not in projects:
                project = self.project_repository.get(task.project_id)
                if project is not None:
                    projects[task.project_id] = project

        scored: list[tuple[int, datetime, Task, PriorityAssessment, Project | None]] = []
        for task, total_subtasks, _ in rows:
            if total_subtasks:
                continue
            project = projects.get(task.project_id) if task.project_id else None
            assessment = self.assess(task, project, now=now)
            due_key = task.due_at or datetime.max.replace(tzinfo=UTC)
            scored.append((assessment.score, due_key, task, assessment, project))
        scored.sort(key=lambda item: (-item[0], item[1], item[2].created_at))

        return [
            PrioritySuggestion(
                task_id=UUID(task.id),
                title=task.title,
                current_priority=TaskPriority(task.priority),
                suggested_priority=assessment.suggested_priority,
                score=assessment.score,
                reasons=assessment.reasons,
                due_at=task.due_at,
                project_id=UUID(task.project_id) if task.project_id else None,
                project_name=project.name if project else None,
                estimated_minutes=task.estimated_minutes,
            )
            for _, _, task, assessment, project in scored[: max(1, min(limit, 30))]
        ]
