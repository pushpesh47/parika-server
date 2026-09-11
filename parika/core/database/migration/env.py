"""
Alembic environment configuration for PARIKA PostgreSQL migrations.

This is loaded by Alembic at runtime and configures the migration environment.
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

# Import PARIKA configuration
from parika.core.configuration.configuration import Configuration
from parika.core.database.config import load_database_config

# This is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate (not used - we write explicit migrations)
target_metadata = None


def get_database_dsn() -> str:
    """Get the database DSN from PARIKA configuration."""
    # Check if we're running in test mode
    import os
    # Allow override via sqlalchemy.url in alembic.ini
    if config.get_main_option("sqlalchemy.url"):
        return config.get_main_option("sqlalchemy.url")
    
    if os.environ.get("PARIKA_TEST_DB") == "1":
        from parika.core.database.config import DatabaseConfig
        # Test credentials MUST come from environment variables
        test_host = os.environ.get("PARIKA_TEST_DATABASE__HOST")
        if test_host is None:
            raise RuntimeError("Test PostgreSQL host not configured. Set PARIKA_TEST_DATABASE__HOST environment variable.")
        test_port_str = os.environ.get("PARIKA_TEST_DATABASE__PORT")
        if test_port_str is None:
            raise RuntimeError("Test PostgreSQL port not configured. Set PARIKA_TEST_DATABASE__PORT environment variable.")
        test_port = int(test_port_str)
        test_database = os.environ.get("PARIKA_TEST_DATABASE__NAME")
        if test_database is None:
            raise RuntimeError("Test PostgreSQL database name not configured. Set PARIKA_TEST_DATABASE__NAME environment variable.")
        test_username = os.environ.get("PARIKA_TEST_DATABASE__USERNAME")
        if test_username is None:
            raise RuntimeError("Test PostgreSQL username not configured. Set PARIKA_TEST_DATABASE__USERNAME environment variable.")
        test_password = os.environ.get("PARIKA_TEST_DATABASE__PASSWORD")
        if test_password is None:
            raise RuntimeError("Test PostgreSQL password not configured. Set PARIKA_TEST_DATABASE__PASSWORD environment variable.")
        return DatabaseConfig(
            enabled=True,
            host=test_host,
            port=test_port,
            database=test_database,
            username=test_username,
            password=test_password,
            pool_min_size=2,
            pool_max_size=10,
            connect_timeout=10.0,
            statement_timeout=0.0,
            application_name="parika_test",
        ).to_dsn()
    
    configuration = Configuration()
    configuration.load()
    db_config = load_database_config(configuration)
    return db_config.to_dsn()


def dsn_to_sqlalchemy_url(dsn: str) -> str:
    """Convert libpq DSN to SQLAlchemy URL format."""
    # If it's already a SQLAlchemy URL (sqlite, postgresql://, etc), return as-is
    if dsn.startswith(("sqlite:", "postgresql:", "postgresql+", "mysql:", "mysql+")):
        return dsn
    
    # Parse key=value pairs (libpq DSN format)
    params = {}
    for part in dsn.split():
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
    
    user = params.get("user", "postgres")
    password = params.get("password", "")
    host = params.get("host", "127.0.0.1")
    port = params.get("port", "5432")
    dbname = params.get("dbname", "parika")
    
    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{dbname}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = dsn_to_sqlalchemy_url(get_database_dsn())
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
    dsn = get_database_dsn()
    url = dsn_to_sqlalchemy_url(dsn)
    
    # Create a SQLAlchemy engine for migrations
    engine = create_engine(url)
    
    with engine.connect() as connection:
        # Create schemas first (before alembic version table) - only for PostgreSQL
        if url.startswith("postgresql"):
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS coding"))
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS cache"))
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS agent"))
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS execution"))
            connection.commit()
        
        # Configure context based on dialect
        if url.startswith("postgresql"):
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_schemas=True,
                version_table_schema="core",
            )
        else:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )
        
        with context.begin_transaction():
            # Set search path to include all our schemas - only for PostgreSQL
            if url.startswith("postgresql"):
                connection.execute(text("SET search_path TO core, coding, cache, agent, execution, public"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()