"""
PARIKA Server - ASGI Application

Constructs the FastAPI application and wires it to exactly one
`ParikaRuntime` per process via a `lifespan` context manager (see
`docs/guides/Running.md` section 12). Contains no business logic: it
only constructs the app, mounts
every router from `parika/api/routers/`, and attaches the
already-constructed Core singletons (`ParikaRuntime`, the API-layer
`Router`, the session store, the authentication backend) to
`app.state` -- mirroring `parika/interfaces/runtime.py`'s own
documented rule that composition-root modules contain no business
logic of their own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from parika.api.auth import build_auth_backend
from parika.api.errors import register_exception_handlers
from parika.api.router_bindings import register_router_bindings
from parika.api.routers import build_v1_router
from parika.api.session_registry import build_default_session_store
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module
from parika.core.execution.owner import CoreExecutionOwner
from parika.core.router.router import Router
from parika.interfaces.runtime import (
    ParikaRuntime,
    build_default_runtime,
    shutdown_runtime,
)
from parika.tools.weather.postgresql_cache import PostgreSQLWeatherCache
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore

from .config import ApiCorsSettings, load_server_settings

# Type alias for session store
SessionStore = PostgreSQLSessionStore


class ParikaRoot:
    """Container for Core resources managed by CoreExecutionOwner."""
    
    def __init__(
        self,
        core_execution_owner: CoreExecutionOwner,
        runtime: ParikaRuntime,
        router: Router,
        session_store: SessionStore,
    ) -> None:
        self.core_execution_owner = core_execution_owner
        self.runtime = runtime
        self.router = router
        self.session_store = session_store


def _default_runtime_factory() -> "ParikaRoot":
    # This is kept for backward compatibility with tests but is not used
    # in normal operation. The actual runtime factory is handled by
    # CoreExecutionOwner.
    from parika.interfaces.runtime import build_default_runtime
    return build_default_runtime()


def create_app(
    *,
    runtime_factory: Callable[[], "ParikaRoot"] | None = None,
) -> FastAPI:
    """
    Construct the PARIKA Server's FastAPI application.

    Args:
        runtime_factory:
            Optional override for how the process's single
            `ParikaRuntime` is constructed, primarily for tests that
            want an isolated runtime (a `tmp_path`-derived data
            directory, `discover_ollama_models=False`, ...). Defaults
            to the existing, unmodified `build_default_runtime()`.
    """
    from typing import Callable
    
    RuntimeFactory = Callable[[], "ParikaRoot"]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Load configuration to get database settings
        from parika.core.configuration.configuration import Configuration
        configuration = Configuration()
        configuration.load()
        db_config = db_config_module.load_database_config(configuration)
        
# Initialize PostgreSQL pools if database is enabled
        sync_pool = None
        if db_config.enabled:
            # Initialize sync pool (needed by CoreExecutionOwner worker thread and API dependencies)
            sync_pool = PoolManager.initialize_sync_pool(db_config)
        
        # Wrap runtime_factory to pass sync_pool if it accepts it
        main_thread_sync_pool = sync_pool  # Capture the main thread's sync_pool
        def runtime_factory_with_pool(sync_pool=None):
            import inspect
            if runtime_factory is not None:
                sig = inspect.signature(runtime_factory)
                if 'sync_pool' in sig.parameters:
                    # Use the sync_pool passed by the worker thread, or fall back to the one captured from main thread
                    pool_to_use = sync_pool if sync_pool is not None else main_thread_sync_pool
                    return runtime_factory(sync_pool=pool_to_use)
                else:
                    return runtime_factory()
            else:
                from parika.interfaces.runtime import build_default_runtime
                return build_default_runtime(sync_pool=main_thread_sync_pool)
        
        # Create CoreExecutionOwner - this will own the Core thread and resources
        core_execution_owner = CoreExecutionOwner(runtime_factory=runtime_factory_with_pool, sync_pool=sync_pool)
        
        # Start the Core worker thread
        core_execution_owner.start()
        
        # Wait for Core resources to be initialized
        if not core_execution_owner.wait_for_ready(timeout=30.0):
            raise RuntimeError("Core execution owner failed to initialize")
            
        # Check if there was an initialization error
        if core_execution_owner._exception is not None:
            raise RuntimeError("Core initialization failed") from core_execution_owner._exception
        
        # Get the initialized Core resources (these are safe to access for read-only purposes)
        # Note: The actual Runtime, SessionStore, and Router are owned by the Core thread
        # and should only be accessed via the CoreExecutionOwner.submit() method
        runtime = core_execution_owner.runtime
        session_store = core_execution_owner.session_store
        core_router = core_execution_owner.router
        
        settings = load_server_settings(runtime.configuration)

        auth_backend = build_auth_backend(
            mode=settings.auth.mode,
            config={
                "api_keys": settings.auth.api_keys,
                "jwt_secret": settings.auth.jwt_secret,
                "jwt_expiry_seconds": settings.auth.jwt_expiry_seconds,
            },
        )

        # Load weather cache TTL from configuration
        cache_ttl_seconds = float(runtime.configuration.get("weather.cache_ttl_seconds", 1200.0))

        # Create shared WeatherCache for the direct Weather API
        # This cache must be shared across all requests to prevent stampedes
        # Use PostgreSQL pool for thread-safe cache
        if sync_pool is not None:
            weather_cache = PostgreSQLWeatherCache(
                sync_pool, ttl_seconds=cache_ttl_seconds
            )
            weather_cache.initialize()
        else:
            raise RuntimeError("PostgreSQL is required for Weather cache")

        # Store references in app.state - but note that the actual Core resources
        # are owned by the CoreExecutionOwner's worker thread
        app.state.core_execution_owner = core_execution_owner
        app.state.runtime = runtime  # For backward compatibility and read-only access
        app.state.router = core_router  # For backward compatibility and read-only access
        app.state.session_store = session_store  # For backward compatibility and read-only access
        app.state.auth_backend = auth_backend
        app.state.server_settings = settings
        app.state.weather_cache = weather_cache  # Shared cache for Weather API
        app.state.sync_pool = sync_pool  # PostgreSQL sync pool for API dependencies

        try:
            yield

        finally:
            # Shutdown the CoreExecutionOwner and its worker thread
            core_execution_owner.shutdown()
            # Shutdown shared WeatherCache
            weather_cache.shutdown()
            app.state.core_execution_owner = None
            app.state.runtime = None
            app.state.router = None
            app.state.session_store = None
            app.state.weather_cache = None
            app.state.sync_pool = None

    app = FastAPI(
        title="PARIKA Server",
        version="1.0.0",
        lifespan=lifespan,
    )

    # `app.state.core_execution_owner` must exist (as `None`) even before `lifespan`
    # runs, so `/api/v1/ready` can answer appropriately during startup.
    app.state.core_execution_owner = None
    app.state.runtime = None
    app.state.router = None
    app.state.session_store = None

    cors_settings = _peek_cors_settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_settings.allow_origins),
        allow_origin_regex=cors_settings.effective_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(build_v1_router())

    _mount_web_client(app)

    return app


def _mount_web_client(app: FastAPI) -> None:
    """
    Serve the static Expense Management Web Client
    (`web/index.html`/`app.js`/`styles.css`) at `/app`, purely as a
    convenience for running everything from one process - the Web
    Client is still an ordinary, independent HTML5/CSS/JavaScript
    bundle that only ever talks to `/api/v1/...` over `fetch()` (see
    `web/index.html`'s own header comment), and `[api.cors]` already
    supports it being served from a different origin/port entirely.

    A no-op (rather than a startup failure) when the `web/` directory
    is absent, e.g. a packaging/deployment that intentionally omits
    it - this mount is additive, never required for the API itself.
    """

    web_directory = Path(__file__).resolve().parents[2] / "web"

    if not web_directory.is_dir():
        return

    app.mount(
        "/app",
        StaticFiles(directory=web_directory, html=True),
        name="expense-web-client",
    )


def _peek_cors_settings() -> ApiCorsSettings:
    """
    Read `[api.cors]` from a throwaway `Configuration` instance so
    `CORSMiddleware` (which must be added before the app starts
    serving, not inside `lifespan`) can be configured without waiting
    for the full `ParikaRuntime` to be built. This never constructs a
    second, competing `Configuration` for the running server -- the
    real `ParikaRuntime`'s own `Configuration` (built inside
    `lifespan`) remains the single source of truth for every other
    setting.
    """

    from parika.core.configuration.configuration import Configuration

    configuration = Configuration()
    configuration.load()

    return load_server_settings(configuration).cors
