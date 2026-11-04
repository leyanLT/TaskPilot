"""Database engine, session factory, and shared SQLAlchemy types."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Persist timestamps as naive UTC and return aware UTC values.

    SQLite does not retain timezone offsets. Normalising at the database
    boundary keeps every stored timestamp unambiguous.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def ensure_sqlite_directory(database_url: str) -> None:
    """Create the parent directory for file-backed SQLite databases."""

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    database_path = Path(url.database)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)


def create_database_engine(database_url: str) -> Engine:
    ensure_sqlite_directory(database_url)
    connect_args: dict[str, object] = {}
    if make_url(database_url).get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False

    engine = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )

    if make_url(database_url).get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency that yields a request-scoped database session."""

    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
