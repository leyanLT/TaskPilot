"""Database schema preparation and automatic Alembic upgrades."""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import make_url

from app import models  # noqa: F401  (registers all ORM models)
from app.config import BACKEND_DIR, Settings
from app.database import Base

logger = logging.getLogger("taskpilot.migrations")

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
BASELINE_REVISION = "0001_v1_0"


def _sqlite_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    path = Path(url.database)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _backup_sqlite_database(database_url: str) -> Path | None:
    path = _sqlite_path(database_url)
    if path is None or not path.exists() or path.stat().st_size == 0:
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    logger.info("Created pre-migration SQLite backup at %s", backup)
    return backup


def _alembic_config(settings: Settings) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["database_url"] = settings.database_url
    return config


def prepare_database(settings: Settings, engine: Engine) -> None:
    """Create or upgrade the schema before the application starts serving."""

    if not settings.database_auto_migrate:
        Base.metadata.create_all(bind=engine)
        return

    tables = set(inspect(engine).get_table_names())
    config = _alembic_config(settings)

    if "alembic_version" in tables:
        with engine.connect() as connection:
            current_revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        head_revision = ScriptDirectory.from_config(config).get_current_head()
        if current_revision != head_revision:
            _backup_sqlite_database(settings.database_url)
            command.upgrade(config, "head")
        return

    if not tables:
        command.upgrade(config, "head")
        return

    if {"tasks", "pending_actions"}.issubset(tables) and "assistant_messages" not in tables:
        # A v1.0 database created by Base.metadata.create_all has no revision
        # marker. Record the baseline before applying data-preserving upgrades.
        _backup_sqlite_database(settings.database_url)
        command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")
        return

    raise RuntimeError(
        "Database schema has no alembic_version and does not match the v1.0 "
        "baseline; refusing to modify it automatically."
    )
