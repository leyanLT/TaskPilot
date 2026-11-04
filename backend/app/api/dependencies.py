"""FastAPI dependencies that compose the service layer."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.services.activity_service import ActivityService
from app.services.assistant_service import AssistantService
from app.services.calendar_service import CalendarService
from app.services.dashboard_service import DashboardService
from app.services.dependency_service import DependencyService
from app.services.focus_service import FocusService
from app.services.insight_service import InsightService
from app.services.notification_service import NotificationService
from app.services.pending_action_service import PendingActionService
from app.services.planning_service import PlanningService
from app.services.preference_service import PreferenceService
from app.services.priority_service import PriorityService
from app.services.project_service import ProjectService
from app.services.recurrence_service import RecurrenceService
from app.services.replan_service import ReplanService
from app.services.report_export_service import ReportExportService
from app.services.report_service import ReportService
from app.services.report_v2_service import ReportV2Service
from app.services.task_service import TaskService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_task_service(
    request: Request,
    session: Session = Depends(get_db),
) -> TaskService:
    settings: Settings = request.app.state.settings
    return TaskService(session, timezone=settings.timezone)


def get_project_service(
    request: Request,
    session: Session = Depends(get_db),
) -> ProjectService:
    settings: Settings = request.app.state.settings
    return ProjectService(session, timezone=settings.timezone)


def get_planning_service(
    request: Request,
    session: Session = Depends(get_db),
) -> PlanningService:
    settings: Settings = request.app.state.settings
    return PlanningService(session, timezone=settings.timezone)


def get_notification_service(
    request: Request,
    session: Session = Depends(get_db),
) -> NotificationService:
    settings: Settings = request.app.state.settings
    return NotificationService(session, timezone=settings.timezone)


def get_activity_service(
    request: Request,
    session: Session = Depends(get_db),
) -> ActivityService:
    settings: Settings = request.app.state.settings
    return ActivityService(session, timezone=settings.timezone)


def get_priority_service(
    request: Request,
    session: Session = Depends(get_db),
) -> PriorityService:
    settings: Settings = request.app.state.settings
    return PriorityService(session, timezone=settings.timezone)


def get_report_service(
    request: Request,
    session: Session = Depends(get_db),
) -> ReportService:
    settings: Settings = request.app.state.settings
    writer = None
    if settings.agent_enabled:
        from app.agent.narrative import build_report_narrative_writer

        writer = build_report_narrative_writer(settings)
    return ReportService(
        session,
        timezone=settings.timezone,
        narrative_writer=writer,
    )


def get_dashboard_service(
    request: Request,
    session: Session = Depends(get_db),
) -> DashboardService:
    settings: Settings = request.app.state.settings
    return DashboardService(session, timezone=settings.timezone)


def get_pending_action_service(
    request: Request,
    session: Session = Depends(get_db),
    task_service: TaskService = Depends(get_task_service),
) -> PendingActionService:
    settings: Settings = request.app.state.settings
    return PendingActionService(
        session,
        task_service,
        ttl_minutes=settings.pending_action_ttl_minutes,
        timezone=settings.timezone,
    )


def get_assistant_service(
    request: Request,
    session: Session = Depends(get_db),
) -> AssistantService:
    settings: Settings = request.app.state.settings
    return AssistantService(session, settings)


# -- V2.0 providers -----------------------------------------------------------


def get_dependency_service(session: Session = Depends(get_db)) -> DependencyService:
    return DependencyService(session)


def get_recurrence_service(
    request: Request,
    session: Session = Depends(get_db),
) -> RecurrenceService:
    settings: Settings = request.app.state.settings
    return RecurrenceService(session, timezone=settings.timezone)


def get_focus_service(
    request: Request,
    session: Session = Depends(get_db),
) -> FocusService:
    settings: Settings = request.app.state.settings
    return FocusService(session, timezone=settings.timezone)


def get_calendar_service(
    request: Request,
    session: Session = Depends(get_db),
) -> CalendarService:
    settings: Settings = request.app.state.settings
    return CalendarService(session, timezone=settings.timezone)


def get_insight_service(
    request: Request,
    session: Session = Depends(get_db),
) -> InsightService:
    settings: Settings = request.app.state.settings
    return InsightService(session, timezone=settings.timezone)


def get_replan_service(
    request: Request,
    session: Session = Depends(get_db),
) -> ReplanService:
    settings: Settings = request.app.state.settings
    return ReplanService(session, timezone=settings.timezone)


def get_preference_service(
    request: Request,
    session: Session = Depends(get_db),
) -> PreferenceService:
    settings: Settings = request.app.state.settings
    return PreferenceService(session, timezone=settings.timezone)


def get_report_v2_service(
    request: Request,
    session: Session = Depends(get_db),
) -> ReportV2Service:
    settings: Settings = request.app.state.settings
    writer = None
    if settings.agent_enabled:
        from app.agent.narrative import build_report_narrative_writer

        writer = build_report_narrative_writer(settings)
    return ReportV2Service(session, timezone=settings.timezone, narrative_writer=writer)


def get_report_export_service(session: Session = Depends(get_db)) -> ReportExportService:
    return ReportExportService(session)
