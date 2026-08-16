"""
PARIKA Core - Core Execution Owner

Manages the dedicated Core worker thread that owns all Core resources
(ParikaRuntime, SqliteSessionStore, Router) and executes all Core work
serialized on that thread.

FastAPI endpoints submit work asynchronously and await results without
blocking the ASGI event loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any, Generic, TypeVar

from parika.core.router.router import Router
from parika.interfaces.runtime import ParikaRuntime
from parika.interfaces.session_store import SqliteSessionStore

T = TypeVar("T")


class _Job(Generic[T]):
    """A unit of work to be executed on the Core worker thread."""

    def __init__(
        self,
        func: Callable[[], T],
        future: Future[T],
        event_loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.func = func
        self.future = future
        self._event_loop = event_loop

    def run(self) -> None:
        """Execute the job and set the result or exception on the future."""
        try:
            result = self.func()
            if not self.future.cancelled():
                # Use call_soon_threadsafe to safely complete the future on the event loop thread
                self._event_loop.call_soon_threadsafe(self.future.set_result, result)
        except Exception as ex:  # noqa: BLE001
            if not self.future.cancelled():
                # Use call_soon_threadsafe to safely complete the future on the event loop thread
                self._event_loop.call_soon_threadsafe(self.future.set_exception, ex)


class CoreExecutionOwner:
    """
    Owns the Core execution thread and all Core-affine resources.

    Exactly one CoreExecutionOwner exists per PARIKA process.
    It creates and manages:
    - One dedicated worker thread
    - One ParikaRuntime (created on the worker thread)
    - One SqliteSessionStore (created on the worker thread)
    - One Router (created on the worker thread)
    
    All Core work is submitted via submit() and executed serially
    on the worker thread. The caller awaits the returned Future.
    """

    def __init__(self, runtime_factory: Callable[[], "ParikaRuntime"] | None = None) -> None:
        self._thread: Thread | None = None
        self._work_queue: Queue[_Job[Any]] = Queue()
        self._ready_event = Event()
        self._shutdown_event = Event()
        self._exception: BaseException | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._started = False

        # Core resources - initialized by the worker thread
        self._runtime: ParikaRuntime | None = None
        self._session_store: SqliteSessionStore | None = None
        self._router: Router | None = None
        
        # Optional runtime factory for tests
        self._runtime_factory = runtime_factory

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the Core worker thread and initialize Core resources.
        
        Must be called exactly once before any work is submitted.
        Safe to call multiple times (subsequent calls are no-ops).
        """
        if self._started:
            return

        self._started = True
        self._thread = Thread(
            target=self._worker_loop,
            name="parika-core-worker",
            daemon=True,
        )
        self._thread.start()

    def wait_for_ready(self, timeout: float | None = None) -> bool:
        """
        Wait for the Core worker thread to initialize resources.
        
        Returns True if resources are ready, False on timeout.
        """
        return self._ready_event.wait(timeout=timeout)

    def shutdown(self) -> None:
        """
        Stop accepting new work and shut down the Core worker thread.
        
        Waits for queued work to complete, then shuts down Core resources
        on the worker thread before terminating the thread.
        Safe to call multiple times.
        """
        if not self._started:
            return

        self._shutdown_event.set()
        
        # Wait for the worker thread to finish
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=30.0)  # Reasonable timeout for shutdown
            
        self._thread = None
        self._started = False

    # ------------------------------------------------------------------
    # Work Submission
    # ------------------------------------------------------------------

    def submit(self, func: Callable[[], T]) -> Future[T]:
        """
        Submit a callable for execution on the Core worker thread.
        
        Args:
            func: A callable that takes no arguments and returns a value.
                  Must be safe to execute on the Core worker thread.
                  
        Returns:
            A Future that will resolve with the function's result or exception.
            
        Raises:
            RuntimeError: If the CoreExecutionOwner is not started or is shut down.
        """
        if not self._started:
            raise RuntimeError("CoreExecutionOwner not started")
            
        if self._shutdown_event.is_set():
            raise RuntimeError("CoreExecutionOwner is shut down")
            
        # Capture the event loop lazily on first submit (will be from ASGI event loop)
        if self._event_loop is None:
            self._event_loop = asyncio.get_event_loop()
        
        # Create a future on the captured event loop (ASGI event loop)
        future: Future[T] = self._event_loop.create_future()
        
        # Create and queue the job with the event loop reference
        job = _Job(func, future, self._event_loop)
        self._work_queue.put(job)
        
        return future

    # ------------------------------------------------------------------
    # Resource Access (for internal use only)
    # ------------------------------------------------------------------

    @property
    def runtime(self) -> ParikaRuntime:
        """
        Get the ParikaRuntime instance.
        
        Only safe to call from the Core worker thread after initialization.
        External code should not access this directly.
        """
        if self._runtime is None:
            raise RuntimeError("Core resources not initialized")
        return self._runtime

    @property
    def session_store(self) -> SqliteSessionStore:
        """
        Get the SqliteSessionStore instance.
        
        Only safe to call from the Core worker thread after initialization.
        External code should not access this directly.
        """
        if self._session_store is None:
            raise RuntimeError("Core resources not initialized")
        return self._session_store

    @property
    def router(self) -> Router:
        """
        Get the Router instance.
        
        Only safe to call from the Core worker thread after initialization.
        External code should not access this directly.
        """
        if self._router is None:
            raise RuntimeError("Core resources not initialized")
        return self._router

    # ------------------------------------------------------------------
    # Internal Implementation
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """
        The main loop of the Core worker thread.
        
        Initializes Core resources, then processes jobs from the queue
        until shutdown is requested and queue is empty.
        """
        try:
            # Initialize Core resources ON THE WORKER THREAD
            self._initialize_core_resources()
            
            # Signal that resources are ready
            self._ready_event.set()
            
            # Process jobs until shutdown and queue is empty
            while True:
                try:
                    # Wait for work with a timeout so we can check shutdown periodically
                    job = self._work_queue.get(timeout=0.1)
                    job.run()
                    self._work_queue.task_done()
                except Empty:
                    # Check if we should exit
                    if self._shutdown_event.is_set() and self._work_queue.empty():
                        break
                    continue
                except Exception as ex:  # noqa: BLE001
                    # Log the exception but continue processing
                    # In a real implementation, we might want to use the logger
                    pass
                    
        except Exception as ex:  # noqa: BLE001
            # Store initialization exception and signal readiness anyway
            # so wait_for_ready doesn't hang forever
            self._exception = ex
            self._ready_event.set()
        finally:
            # Cleanup Core resources ON THE WORKER THREAD
            self._shutdown_core_resources()

    def _initialize_core_resources(self) -> None:
        """
        Initialize Core resources. Must be called ONLY from the worker thread.
        """
        from parika.api.router_bindings import register_router_bindings
        from parika.core.router.router import Router
        from parika.interfaces.runtime import build_default_runtime
        from parika.api.session_registry import build_default_session_store
        
        # Create Runtime on the worker thread
        # Use the runtime_factory if provided, otherwise default
        if hasattr(self, '_runtime_factory') and self._runtime_factory is not None:
            self._runtime = self._runtime_factory()
        else:
            self._runtime = build_default_runtime()
        
        # Create SessionStore on the worker thread using configuration-driven path
        self._session_store = build_default_session_store(self._runtime)
        
        # Create Router on the worker thread
        self._router = Router(event_bus=self._runtime.event_bus, logger=self._runtime.logger)
        
        # Register router bindings (this binds the handlers to the router)
        register_router_bindings(self._router, self._runtime, self._session_store)

    def _shutdown_core_resources(self) -> None:
        """
        Shutdown Core resources. Must be called ONLY from the worker thread.
        """
        from parika.interfaces.runtime import shutdown_runtime
        
        # Shutdown in reverse order of initialization
        if self._session_store is not None:
            self._session_store.shutdown()
            self._session_store = None
            
        if self._runtime is not None:
            shutdown_runtime(self._runtime)
            self._runtime = None
            
        # Router doesn't need explicit shutdown
        self._router = None