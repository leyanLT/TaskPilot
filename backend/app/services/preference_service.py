"""Single-row user preferences (timezone, working capacity, focus default)."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import utc_now
from app.exceptions import DatabaseOperationError, InvalidRecurrenceError
from app.models import UserPreference
from app.repositories.v2_repository import PreferenceRepository
from app.schemas_v2 import PreferencesRead, PreferencesUpdate

DEFAULT_WORKDAYS = [0, 1, 2, 3, 4]
DEFAULT_AVAILABLE_MINUTES = 300
DEFAULT_FOCUS_MINUTES = 25


class PreferenceService:
    def __init__(self, session: Session, *, timezone: ZoneInfo) -> None:
        self.session = session
        self.timezone = timezone
        self.repository = PreferenceRepository(session)

    def _row(self) -> UserPreference:
        row = self.repository.get()
        if row is None:
            row = UserPreference(
                id="default",
                timezone=self.timezone.key,
                daily_available_minutes=DEFAULT_AVAILABLE_MINUTES,
                workdays=DEFAULT_WORKDAYS,
                default_focus_minutes=DEFAULT_FOCUS_MINUTES,
                reminder_prefs={"due_soon_hours": 24, "today_todo": True},
                dismissed_insights=[],
            )
            try:
                self.repository.save(row)
                self.session.commit()
            except SQLAlchemyError as exc:
                self.session.rollback()
                raise DatabaseOperationError() from exc
        return row

    def _view(self, row: UserPreference) -> PreferencesRead:
        return PreferencesRead(
            timezone=row.timezone,
            daily_available_minutes=row.daily_available_minutes,
            workdays=list(row.workdays or DEFAULT_WORKDAYS),
            default_focus_minutes=row.default_focus_minutes,
            reminder_prefs=dict(row.reminder_prefs or {}),
            updated_at=row.updated_at,
        )

    def get(self) -> PreferencesRead:
        return self._view(self._row())

    def update(self, data: PreferencesUpdate) -> PreferencesRead:
        row = self._row()
        payload = data.model_dump(exclude_unset=True)
        if "timezone" in payload and payload["timezone"]:
            try:
                ZoneInfo(str(payload["timezone"]))
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise InvalidRecurrenceError("时区名称无效。") from exc
            row.timezone = str(payload["timezone"])
        for field in (
            "daily_available_minutes",
            "default_focus_minutes",
            "reminder_prefs",
        ):
            if field in payload and payload[field] is not None:
                setattr(row, field, payload[field])
        if "workdays" in payload and payload["workdays"] is not None:
            row.workdays = sorted({int(day) for day in payload["workdays"]})
        row.updated_at = utc_now()
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise DatabaseOperationError() from exc
        return self._view(row)
