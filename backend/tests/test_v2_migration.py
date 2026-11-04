"""V2.0 migration: upgrading a V1.5 database keeps every existing row."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.config import BACKEND_DIR, Settings

MIGRATIONS = BACKEND_DIR / "migrations"


def _config(settings: Settings) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["database_url"] = settings.database_url
    return config


def test_v1_5_rows_survive_the_v2_upgrade(tmp_path: Path) -> None:
    database = tmp_path / "v15.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database.as_posix()}",
        database_auto_migrate=True,
        app_timezone="Asia/Shanghai",
    )
    config = _config(settings)
    command.upgrade(config, "0003_v1_5")

    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, description, status, start_date, due_date, "
            "created_at, updated_at) VALUES ('p1', '老项目', NULL, 'active', NULL, NULL, ?, ?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO tasks (id, title, description, status, due_at, created_at, updated_at, "
            "project_id, parent_id, priority, estimated_minutes, position, completed_at) "
            "VALUES ('t1', '老任务', '旧数据', 'pending', NULL, ?, ?, 'p1', NULL, 'high', 45, 0, NULL)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO pending_actions (id, action_type, status, payload, summary, "
            "result_task_id, created_at, expires_at, resolved_at) "
            "VALUES ('a1', 'create_task', 'pending', '{}', '旧操作', NULL, ?, ?, NULL)",
            (now, now),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert revision == "0005_v2_1"
        task = connection.execute(
            "SELECT title, project_id, priority, estimated_minutes, recurrence_rule_id, "
            "occurrence_date FROM tasks WHERE id = 't1'"
        ).fetchone()
        assert task == ("老任务", "p1", "high", 45, None, None)
        action = connection.execute(
            "SELECT action_type, summary, status FROM pending_actions WHERE id = 'a1'"
        ).fetchone()
        assert action == ("create_task", "旧操作", "pending")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "task_dependencies",
            "recurrence_rules",
            "focus_sessions",
            "plan_revisions",
            "user_preferences",
        }.issubset(tables)
        project = connection.execute("SELECT name FROM projects WHERE id = 'p1'").fetchone()
        assert project == ("老项目",)


def test_downgrade_and_reupgrade_keep_data(tmp_path: Path) -> None:
    database = tmp_path / "v20.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database.as_posix()}",
        database_auto_migrate=True,
        app_timezone="Asia/Shanghai",
    )
    config = _config(settings)
    command.upgrade(config, "head")

    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO tasks (id, title, description, status, due_at, created_at, updated_at, "
            "project_id, parent_id, priority, estimated_minutes, position, completed_at, "
            "recurrence_rule_id, occurrence_date) "
            "VALUES ('t2', '新任务', NULL, 'pending', NULL, ?, ?, NULL, NULL, 'medium', NULL, 0, "
            "NULL, NULL, NULL)",
            (now, now),
        )
        connection.commit()

    command.downgrade(config, "0003_v1_5")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT title FROM tasks WHERE id = 't2'").fetchone() == (
            "新任务",
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
        assert "recurrence_rule_id" not in columns

    command.upgrade(config, "head")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT title, recurrence_rule_id FROM tasks WHERE id = 't2'"
        ).fetchone() == ("新任务", None)
