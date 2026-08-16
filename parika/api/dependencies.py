"""
PARIKA API - Shared FastAPI Dependencies

The transport-local dependency-injection seam: FastAPI's
`Depends()` is used here, and only here, to retrieve the 
`CoreExecutionOwner` singleton that `parika/server/app.py` 
attaches to `app.state` at startup. Route handlers use this
to submit Core work asynchronously without blocking the 
ASGI event loop.

`app.state.runtime` (the `ParikaRuntime` itself) is deliberately not
exposed through a matching `get_runtime()` dependency here: every
route handler in `parika/api/routers/` reaches Core exclusively by
submitting work through the `CoreExecutionOwner` returned by 
`get_core_execution_owner()` below, never by touching `ParikaRuntime`
directly (see `docs/development/Integration_Checklist.md` section 11).

API-owned Expense dependencies:
These create independent ExpenseService/ExpenseStorage instances with
their own SQLite connections for the direct Expense API path, which
must not go through CoreExecutionOwner.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Generator

from fastapi import Request

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.execution.owner import CoreExecutionOwner
from parika.core.logger.logger import Logger
from parika.interfaces.runtime import ParikaRuntime

from parika.tools.expense.config import load_expense_config
from parika.tools.expense.service import ExpenseService
from parika.tools.expense.storage import ExpenseStorage


def get_core_execution_owner(request: Request) -> CoreExecutionOwner:
    """
    Retrieve the CoreExecutionOwner instance that manages the 
    dedicated Core worker thread and all Core-affine resources.
    
    Route handlers use this to submit Core work asynchronously:
    
        core_owner = Depends(get_core_execution_owner)
        future = core_owner.submit(lambda: core_router.dispatch(request))
        result = await future
    """
    return request.app.state.core_execution_owner


def get_runtime(request: Request) -> ParikaRuntime:
    """
    Retrieve the ParikaRuntime instance for direct read-only access.
    
    This is for endpoints that only need to query runtime managers
    (ProviderManager, ToolManager, CapabilityRegistry, ModuleManager,
    Configuration, ResourceManager, etc.) without executing Core work.
    
    These endpoints do NOT go through CoreExecutionOwner and remain
    responsive even when Core is busy with long-running operations.
    
    Note: The runtime is owned by the Core worker thread. Read-only
    access to immutable/mostly-immutable data structures is safe.
    Callers must NOT mutate Core state or submit work through the
    runtime's managers directly.
    """
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise RuntimeError("Runtime not initialized")
    return runtime


def get_expense_service(request: Request) -> Generator[ExpenseService, None, None]:
    """
    FastAPI generator dependency for API-owned ExpenseService.

    Creates a NEW ExpenseStorage with its own SQLite connection,
    initializes it, creates an ExpenseService, yields it to the
    request handler, then shuts down the storage after the request.

    This is independent of the Core-owned ExpenseService and does
    not go through CoreExecutionOwner.
    """
    # Get database path from configuration
    # Use the runtime's configuration which has the correct data_directory (for tests)
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is not None and hasattr(runtime, "configuration"):
        configuration = runtime.configuration
    else:
        configuration = Configuration()
        configuration.load()
    
    # Use the runtime's data_directory override if available
    data_directory = getattr(configuration, "_data_directory_override", None)
    if data_directory is not None:
        data_directory = Path(data_directory)
    else:
        data_directory = configuration.get_project_root() / configuration.get("data.directory", "data")
    database_path = data_directory / "expense.sqlite3"

    # Create API-owned storage and service
    storage = ExpenseStorage(database_path=database_path)
    storage.initialize()

    event_bus = EventBus(Logger(configuration))
    logger = Logger(configuration).get_logger("parika.api.expense")
    expense_config = load_expense_config(configuration)

    service = ExpenseService(
        storage=storage,
        event_bus=event_bus,
        logger=Logger(configuration),
        config=expense_config,
    )

    try:
        yield service
    finally:
        storage.shutdown()