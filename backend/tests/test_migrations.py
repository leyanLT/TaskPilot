"""Alembic baseline, automatic upgrade, and data-preservation tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from app.config import Settings
from app.database import create_database_engine
from app.migrations import _alembic_config, prepare_database
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def _settings(path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{path.as_posix()}",
        database_auto_migrate=True,
    )


def _head_revision(settings: Settings) -> str | None:
    return ScriptDirectory.from_config(_alembic_config(settings)).get_current_head()


def test_fresh_database_is_migrated_to_head(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    settings = _settings(path)
    engine = create_engine(settings.database_url)
    prepare_database(settings, engine)

    tables = set(inspect(engine).get_table_names())
    assert {
        "tasks",
        "pending_actions",
        "assistant_messages",
        "alembic_version",
        "projects",
        "task_activities",
        "daily_plans",
        "plan_items",
        "notifications",
        "reports",
    } <= tables
    task_columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    assert {
        "project_id",
        "parent_id",
        "priority",
        "estimated_minutes",
        "position",
        "completed_at",
    } <= task_columns
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert revision == _head_revision(settings)
    engine.dispose()


def test_v1_database_is_stamped_and_preserved(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    settings = _settings(path)
    config = _alembic_config(settings)
    command.upgrade(config, "0001_v1_0")

    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tasks
                    (id, title, description, status, due_at, created_at, updated_at)
                VALUES
                    ('old-task', '旧任务', NULL, 'pending', NULL,
                     '2026-01-01 00:00:00', '2026-01-01 00:00:00')
                """
            )
        )
        connection.execute(text("DROP TABLE alembic_version"))
    engine.dispose()

    prepare_database(settings, create_engine(settings.database_url))
    upgraded = create_engine(settings.database_url)
    with upgraded.connect() as connection:
        title = connection.execute(text("SELECT title FROM tasks")).scalar()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        action = connection.execute(
            text(
                """
                INSERT INTO pending_actions
                    (id, action_type, status, payload, summary,
                     result_task_id, created_at, expires_at, resolved_at)
                VALUES
                    ('action-new', 'update_task', 'pending', '{}', 'test',
                     NULL, '2026-01-01 00:00:00', '2999-01-01 00:00:00', NULL)
                """
            )
        )
        assert action.rowcount == 1
    assert title == "旧任务"
    assert revision == _head_revision(settings)
    backups_after_upgrade = set(path.parent.glob(path.name + ".bak-*"))
    assert backups_after_upgrade
    upgraded.dispose()

    # A second startup at head must not create another backup.
    prepare_database(settings, create_engine(settings.database_url))
    assert set(path.parent.glob(path.name + ".bak-*")) == backups_after_upgrade


def test_new_action_type_constraint_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "constraint.db"
    settings = _settings(path)
    engine = create_engine(settings.database_url)
    prepare_database(settings, engine)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO pending_actions
                        (id, action_type, status, payload, summary,
                         result_task_id, created_at, expires_at, resolved_at)
                    VALUES
                        ('bad', 'unknown_action', 'pending', '{}', 'bad',
                         NULL, '2026-01-01 00:00:00', '2999-01-01 00:00:00', NULL)
                    """
                )
            )
    engine.dispose()


def test_sqlite_backup_is_a_real_database_copy(tmp_path: Path) -> None:
    path = tmp_path / "backup.db"
    settings = _settings(path)
    config = _alembic_config(settings)
    command.upgrade(config, "0001_v1_0")
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO tasks
            (id, title, description, status, due_at, created_at, updated_at)
        VALUES ('backup-task', '保留我', NULL, 'pending', NULL,
                '2026-01-01 00:00:00', '2026-01-01 00:00:00')
        """
    )
    connection.commit()
    connection.execute("DROP TABLE alembic_version")
    connection.commit()
    connection.close()

    prepare_database(settings, create_engine(settings.database_url))
    backups = list(path.parent.glob(path.name + ".bak-*"))
    assert backups
    backup_connection = sqlite3.connect(backups[0])
    assert backup_connection.execute("SELECT title FROM tasks").fetchone()[0] == "保留我"
    backup_connection.close()


def test_v12_database_upgrades_to_v15_preserving_data(tmp_path: Path) -> None:
    path = tmp_path / "v12.db"
    settings = _settings(path)
    command.upgrade(_alembic_config(settings), "0002_ai_upgrade")
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tasks
                    (id, title, description, status, due_at, created_at, updated_at)
                VALUES
                    ('pending-task', '旧待办', NULL, 'pending', NULL,
                     '2026-01-01 00:00:00', '2026-01-02 00:00:00'),
                    ('done-task', '旧完成', NULL, 'completed', NULL,
                     '2026-01-01 00:00:00', '2026-01-05 08:30:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO pending_actions
                    (id, action_type, status, payload, summary,
                     result_task_id, created_at, expires_at, resolved_at)
                VALUES
                    ('old-action', 'update_task', 'pending', '{}', '旧操作',
                     NULL, '2026-01-01 00:00:00', '2999-01-01 00:00:00', NULL)
                """
            )
        )
    engine.dispose()

    prepare_database(settings, create_engine(settings.database_url))
    upgraded = create_engine(settings.database_url)
    task_columns = {column["name"] for column in inspect(upgraded).get_columns("tasks")}
    assert "parent_id" in task_columns and "completed_at" in task_columns
    with upgraded.connect() as connection:
        rows = {
            row[0]: row
            for row in connection.execute(
                text("SELECT id, title, status, priority, position, completed_at FROM tasks")
            )
        }
        assert set(rows) == {"pending-task", "done-task"}
        assert rows["pending-task"][1] == "旧待办"
        assert rows["pending-task"][3] == "medium"
        assert rows["pending-task"][4] == 0
        assert rows["pending-task"][5] is None
        assert rows["done-task"][3] == "medium"
        assert rows["done-task"][5] is not None
        old_action = connection.execute(
            text("SELECT action_type, summary FROM pending_actions WHERE id='old-action'")
        ).one()
        assert old_action[0] == "update_task"
        assert old_action[1] == "旧操作"
        connection.execute(
            text(
                """
                INSERT INTO pending_actions
                    (id, action_type, status, payload, summary,
                     result_task_id, created_at, expires_at, resolved_at)
                VALUES
                    ('new-action', 'create_task_breakdown', 'pending', '{}', '新操作',
                     NULL, '2026-01-01 00:00:00', '2999-01-01 00:00:00', NULL)
                """
            )
        )
    assert set(path.parent.glob(path.name + ".bak-*"))
    upgraded.dispose()


def test_v15_foreign_keys_cascade_after_migration(tmp_path: Path) -> None:
    path = tmp_path / "fk.db"
    settings = _settings(path)
    prepare_database(settings, create_engine(settings.database_url))
    engine = create_database_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects (id, name, status, created_at, updated_at) "
                "VALUES ('p1', '项目', 'active', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tasks
                    (id, title, status, priority, position, project_id, created_at, updated_at)
                VALUES
                    ('parent', '父', 'pending', 'medium', 0, 'p1',
                     '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
                    ('child', '子', 'pending', 'medium', 0, 'p1',
                     '2026-01-01 00:00:00', '2026-01-01 00:00:00')
                """
            )
        )
        connection.execute(text("UPDATE tasks SET parent_id='parent' WHERE id='child'"))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO notifications (id, type, task_id, message, dedupe_key, created_at) "
                "VALUES ('n1', 'today_todo', 'child', '提醒', 'k1', '2026-01-01 00:00:00')"
            )
        )
        connection.execute(text("DELETE FROM tasks WHERE id='parent'"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM tasks")).scalar() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM notifications")).scalar() == 0
        connection.execute(
            text(
                "INSERT INTO tasks (id, title, status, priority, position, project_id, "
                "created_at, updated_at) VALUES ('t3', '三', 'pending', 'medium', 0, 'p1', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM projects WHERE id='p1'"))
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT project_id FROM tasks WHERE id='t3'")).scalar() is None
        )
    engine.dispose()
