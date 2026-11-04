"""Alembic environment for TaskPilot.

The database URL can come from a programmatic config attribute, the
``sqlalchemy.url`` option, or the application settings used by the CLI.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app import models  # noqa: F401  (registers all ORM models)
from app.config import get_settings
from app.database import Base, create_database_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    database_url = (
        config.attributes.get("database_url")
        or config.get_main_option("sqlalchemy.url")
        or get_settings().database_url
    )
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    database_url = (
        config.attributes.get("database_url")
        or config.get_main_option("sqlalchemy.url")
        or get_settings().database_url
    )
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as online_connection:
            is_sqlite = online_connection.dialect.name == "sqlite"
            if is_sqlite:
                # SQLite batch mode recreates tables. Foreign keys must be
                # disabled while referencing tables are rebuilt, otherwise the
                # drop/rename step can cascade or reject the copy.
                online_connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            context.configure(
                connection=online_connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
            if is_sqlite:
                # SQLite DDL is non-transactional, so Alembic does not wrap it
                # in BEGIN/COMMIT. The INSERT statements inside migrations do
                # open an implicit transaction; commit it explicitly before
                # restoring the pragma and closing the connection.
                online_connection.commit()
                online_connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
