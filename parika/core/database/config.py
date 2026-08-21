"""
PARIKA Database Configuration

Configuration for the PostgreSQL persistence layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class DatabaseConfig:
    """PostgreSQL connection and pool configuration."""

    enabled: bool = True
    host: str
    port: int
    database: str
    username: str
    password: str
    pool_min_size: int = 2
    pool_max_size: int = 10
    connect_timeout: float = 10.0
    statement_timeout: float = 0.0
    application_name: str = "parika"
    sslmode: str = "prefer"

    def to_dsn(self) -> str:
        """Build a PostgreSQL DSN string."""
        parts = [
            f"host={self.host}",
            f"port={self.port}",
            f"dbname={self.database}",
            f"user={self.username}",
        ]
        if self.password:
            parts.append(f"password={self.password}")
        if self.connect_timeout:
            parts.append(f"connect_timeout={int(self.connect_timeout)}")
        if self.statement_timeout:
            parts.append(f"options=-c statement_timeout={int(self.statement_timeout * 1000)}")
        if self.application_name:
            parts.append(f"application_name={self.application_name}")
        if self.sslmode:
            parts.append(f"sslmode={self.sslmode}")
        return " ".join(parts)

    def to_async_dsn(self) -> str:
        """Build a PostgreSQL DSN string for async connections (same as sync)."""
        return self.to_dsn()


def load_database_config(configuration: "Configuration | None" = None) -> DatabaseConfig:
    """
    Load database configuration from Configuration.

    PostgreSQL is REQUIRED. If not properly configured, will raise an error.
    """
    if configuration is None:
        raise RuntimeError("Configuration is required for database setup. PostgreSQL is mandatory.")

    # Database connection identity MUST come from environment variables
    host = configuration.get("database.host")
    if host is None:
        raise RuntimeError("PostgreSQL host not configured. Set PARIKA_DATABASE__HOST environment variable.")

    port = configuration.get("database.port")
    if port is None:
        raise RuntimeError("PostgreSQL port not configured. Set PARIKA_DATABASE__PORT environment variable.")

    database = configuration.get("database.database")
    if database is None:
        raise RuntimeError("PostgreSQL database name not configured. Set PARIKA_DATABASE__DATABASE environment variable.")

    username = configuration.get("database.username")
    if username is None:
        raise RuntimeError("PostgreSQL username not configured. Set PARIKA_DATABASE__USERNAME environment variable.")

    password = configuration.get("database.password")
    if password is None:
        raise RuntimeError("PostgreSQL password not configured. Set PARIKA_DATABASE__PASSWORD environment variable.")

    return DatabaseConfig(
        enabled=configuration.get("database.enabled", True),
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        pool_min_size=configuration.get("database.pool_min_size", 2),
        pool_max_size=configuration.get("database.pool_max_size", 10),
        connect_timeout=configuration.get("database.connect_timeout", 10.0),
        statement_timeout=configuration.get("database.statement_timeout", 0.0),
        application_name=configuration.get("database.application_name", "parika"),
    )