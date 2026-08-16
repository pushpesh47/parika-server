"""
PARIKA API - Session Store Wiring

Small helper that constructs the same `SqliteSessionStore`-backed
session persistence the native Console already uses
(`parika/console/app.py:_default_session_store`), for the API layer's
chat endpoints. Kept as a tiny, independent helper here rather than
importing a Console-private function, since the API layer must never
depend on `parika/console/`: the Console is not an API client and the
API layer is not permitted to depend on it (see
`docs/architecture/PARIKA_Architecture_Specification_v1.0.md`,
"PARIKA Console" section).
"""

from __future__ import annotations

from parika.interfaces.runtime import ParikaRuntime
from parika.interfaces.session_store import SqliteSessionStore


def build_default_session_store(runtime: ParikaRuntime) -> SqliteSessionStore:
    """
    Construct and initialize the default `data/sessions.sqlite3`
    store, exactly as the CLI's own `_default_session_store()` does.
    """

    store = SqliteSessionStore(
        runtime.configuration.get_project_root()
        / runtime.configuration.get("data.directory", "data")
        / "sessions.sqlite3"
    )
    store.initialize()

    return store
