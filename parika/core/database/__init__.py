"""
PARIKA Database Module

PostgreSQL persistence layer for PARIKA.
"""

from __future__ import annotations

from .config import DatabaseConfig, load_database_config
from .pool import PoolManager

__all__ = [
    "DatabaseConfig",
    "load_database_config",
    "PoolManager",
]