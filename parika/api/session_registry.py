"""
PARIKA API - Session Store Wiring

Small helper that constructs the session persistence store.
Uses PostgreSQL (required).
"""
from __future__ import annotations

from parika.interfaces.runtime import ParikaRuntime
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module


def build_default_session_store(runtime: ParikaRuntime) -> PostgreSQLSessionStore:
    """
    Construct and initialize the default session store.

    Uses PostgreSQL (required).
    """
    configuration = runtime.configuration
    db_config = db_config_module.load_database_config(configuration)
    
    # Use PostgreSQL
    pool = PoolManager.get_sync_pool()
    if pool is None:
        raise RuntimeError("PostgreSQL enabled but sync pool not initialized")
    return PostgreSQLSessionStore(pool)