"""
Alembic test environment configuration for PARIKA PostgreSQL test migrations.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, text

# Add the project root to the path so we can import parika modules
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

# This is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate (not used - we write explicit migrations)
target_metadata = None


def get_database_url() -> str:
    """Get the database URL from alembic config."""
    # First try sqlalchemy.url from config
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    
    # Fallback to PARIKA configuration
    from parika.core.configuration.configuration import Configuration
    from parika.core.database.config import load_database_config
    configuration = Configuration()
    configuration.load()
    db_config = load_database_config(configuration)
    return db_config.to_dsn()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = get_database_url()

    # Create a SQLAlchemy engine for migrations
    engine = create_engine(url)

    with engine.connect() as connection:
        # Create schemas first (before alembic version table)
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS coding"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS cache"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS agent"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS execution"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema="core",
        )

        with context.begin_transaction():
            # Set search path to include all our schemas
            connection.execute(text("SET search_path TO core, coding, cache, agent, execution, public"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
