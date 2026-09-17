"""
PARIKA Interfaces - Runtime

Defines `ParikaRuntime`, the reusable composition-root handle shared
by every PARIKA Interface (CLI today; REST, Desktop, Web, and Voice in
the future), and `build_default_runtime()`, which wires the frozen
Core in the order mandated by
`PARIKA_Architecture_Specification_v1.0.md` section 5.1 ("Core
Implementation Order") and registers the built-in Modules and
Providers this milestone ships.

`ParikaRuntime` itself contains no business logic: it is only a
typed bundle of already-constructed Core singletons. Interfaces use
`runtime.brain` for the actual request/response pipeline and the
remaining Core managers only for read-only introspection (slash
commands such as `/status`, `/providers`, `/tools`, `/modules`, and
`/capabilities`), never to execute business logic directly. Brain
itself is never modified by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
from parika.core.agent_orchestrator.agent_profile import AgentProfile, AgentSpecialization
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_resolver import AgentResolver
from parika.core.brain.brain import Brain
from parika.core.capability_registry.capability_category import CapabilityCategory
from types import MappingProxyType
from parika.core.capability_executor.capability_executor import (
    CapabilityExecutor,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.database.config import load_database_config
from parika.core.database.pool import PoolManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_manager import HealthManager
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.logger.logger import Logger
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.metrics_manager.metrics_manager import MetricsManager
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import (
    WorkspacePermissionManager,
)
from parika.core.permission_manager.workspace_permission_prompt import (
    WorkspacePermissionPrompt,
)
from parika.core.permission_manager.workspace_trust_store import RuntimeTrustWriter
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.service_container.service_container import ServiceContainer
from parika.core.state_manager.state_manager import StateManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.ui_context.projector import UIContextProjector
from parika.core.context_manager.context_manager import ContextManager
from parika.modules.chat.driver import ChatModuleDriver
from parika.modules.chat.manifest import CHAT_MODULE_ID, create_chat_module
from parika.modules.coding.driver import CodingModuleDriver
from parika.modules.coding.manifest import CODING_MODULE_ID, create_coding_module
from parika.modules.coding_agent.module_driver import CodingAgentModuleDriver
from parika.modules.coding_agent.manifest import (
    CODING_AGENT_MODULE_ID,
    create_coding_agent_module,
)
from parika.modules.currency.driver import CurrencyModuleDriver
from parika.modules.currency.manifest import (
    CURRENCY_MODULE_ID,
    create_currency_module,
)
from parika.modules.expense.driver import ExpenseModuleDriver
from parika.modules.expense.manifest import (
    EXPENSE_MODULE_ID,
    create_expense_module,
)
from parika.tools.expense.config import load_expense_config
from parika.tools.expense.service import ExpenseService
from parika.tools.expense.postgresql_storage import PostgreSQLExpenseStorage
from parika.modules.filesystem.driver import FilesystemModuleDriver
from parika.modules.filesystem.manifest import (
    FILESYSTEM_MODULE_ID,
    create_filesystem_module,
)
from parika.modules.generation.module_driver import GenerationModuleDriver
from parika.modules.generation.manifest import (
    GENERATION_MODULE_ID,
    create_generation_module,
)
from parika.modules.media.module_driver import MediaModuleDriver
from parika.modules.media.manifest import MEDIA_MODULE_ID, create_media_module
from parika.tools.media.config import load_media_config
from parika.tools.media.connection_registry import MediaConnectionRegistry
from parika.tools.media.resolution import MediaResolver
from parika.tools.media.security import LocalMediaPathSecurity, LocalMediaPathSecurityConfig
from parika.tools.media.state_store import MediaStateStore
from parika.modules.repository_intelligence.driver import (
    RepositoryIntelligenceModuleDriver,
)
from parika.modules.repository_intelligence.manifest import (
    REPOSITORY_INTELLIGENCE_MODULE_ID,
    create_repository_intelligence_module,
)
from parika.modules.shell.driver import ShellModuleDriver
from parika.modules.shell.manifest import SHELL_MODULE_ID, create_shell_module
from parika.modules.experience.driver import ExperienceModuleDriver
from parika.modules.experience.experience_store import ExperienceStore
from parika.modules.experience.manifest import (
    EXPERIENCE_MODULE_ID,
    create_experience_module,
)
from parika.modules.knowledge_indexing.driver import KnowledgeIndexingModuleDriver
from parika.modules.knowledge_indexing.manifest import (
    KNOWLEDGE_INDEXING_MODULE_ID,
    create_knowledge_indexing_module,
)
from parika.modules.memory.driver import MemoryModuleDriver
from parika.modules.memory.manifest import MEMORY_MODULE_ID, create_memory_module
from parika.modules.news.driver import NewsModuleDriver
from parika.modules.news.manifest import NEWS_MODULE_ID, create_news_module
from parika.modules.document.module_driver import DocumentModuleDriver
from parika.modules.document.manifest import (
    DOCUMENT_MODULE_ID,
    create_document_module,
)
from parika.modules.ocr.module_driver import OcrModuleDriver
from parika.modules.ocr.manifest import OCR_MODULE_ID, create_ocr_module
from parika.modules.runtime_info.driver import RuntimeInfoModuleDriver
from parika.modules.runtime_info.manifest import (
    RUNTIME_INFO_MODULE_ID,
    create_runtime_info_module,
)
from parika.modules.vision.module_driver import VisionModuleDriver
from parika.modules.vision.manifest import VISION_MODULE_ID, create_vision_module
from parika.modules.video.module_driver import VideoModuleDriver
from parika.modules.video.manifest import VIDEO_MODULE_ID, create_video_module
from parika.modules.voice.module_driver import VoiceModuleDriver
from parika.modules.voice.manifest import VOICE_MODULE_ID, create_voice_module
from parika.modules.voice.config import load_voice_config
from parika.modules.voice.language import (
    VoiceLanguagePreference,
    VoiceLanguagePreferenceStore,
)
from parika.modules.voice.operation_registry import TtsOperationRegistry
from parika.modules.weather.driver import WeatherModuleDriver
from parika.modules.weather.manifest import (
    WEATHER_MODULE_ID,
    create_weather_module,
)
from parika.modules.web_search.driver import WebSearchModuleDriver
from parika.modules.web_search.manifest import (
    WEB_SEARCH_MODULE_ID,
    create_web_search_module,
)
from parika.modules.autonomous.driver import load_autonomous_module
from parika.modules.autonomous.manifest import AUTONOMOUS_MODULE_ID, create_autonomous_module
from parika.providers.ollama.driver import (
    DEFAULT_BASE_URL,
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    OllamaProviderDriver,
)
from parika.providers.ollama.exceptions import OllamaProviderError
from parika.providers.ollama.manifest import (
    OLLAMA_PROVIDER_ID,
    create_ollama_provider,
)
from parika.providers.ollama.transport import (
    OllamaTransport,
    UrllibOllamaTransport,
)
from parika.providers.comfyui.driver import (
    DEFAULT_BASE_URL as COMFYUI_DEFAULT_BASE_URL,
    DEFAULT_CONNECT_TIMEOUT_SECONDS as COMFYUI_DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS as COMFYUI_DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS as COMFYUI_DEFAULT_POLL_TIMEOUT_SECONDS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS as COMFYUI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ComfyUIProviderDriver,
)
from parika.providers.comfyui.exceptions import ComfyUIProviderError
from parika.providers.comfyui.manifest import (
    COMFYUI_PROVIDER_ID,
    create_comfyui_provider,
)
from parika.providers.comfyui.model_config import ComfyUIModelConfig
from parika.providers.comfyui.transport import (
    ComfyUITransport,
    UrllibComfyUITransport,
)
from parika.providers.local_speech.config import load_local_speech_config
from parika.providers.local_speech.driver import LocalSpeechProviderDriver
from parika.providers.local_speech.exceptions import LocalSpeechProviderError
from parika.providers.local_speech.manifest import (
    LOCAL_SPEECH_PROVIDER_ID,
    create_local_speech_provider,
)
from parika.providers.openai_compatible.config import load_openai_compatible_configs
from parika.providers.openai_compatible.driver import OpenAICompatibleProviderDriver
from parika.providers.openai_compatible.exceptions import OpenAICompatibleError
from parika.core.provider_manager.provider import Provider


@dataclass(slots=True, kw_only=True)
class ParikaRuntime:
    """
    Reusable, already-wired handle to the PARIKA Core.

    Every Interface (CLI, and in the future REST, Desktop, Web, and
    Voice) is constructed with one `ParikaRuntime`. The Interface
    layer sends every user-facing request through `runtime.brain`;
    the remaining managers are exposed only for read-only
    introspection by slash-command-style diagnostics that
    intentionally do not go through Brain.
    """

    configuration: Configuration
    logger: Logger
    event_bus: EventBus
    service_container: ServiceContainer

    state_manager: StateManager
    resource_manager: ResourceManager
    health_manager: HealthManager
    metrics_manager: MetricsManager

    context_manager: ContextManager

    capability_registry: CapabilityRegistry
    capability_resolver: CapabilityResolver
    policy_engine: PolicyEngine
    permission_manager: PermissionManager
    workspace_permissions: WorkspacePermissionManager

    memory_manager: MemoryManager
    knowledge_manager: KnowledgeManager

    provider_manager: ProviderManager
    tool_manager: ToolManager
    module_manager: ModuleManager

    capability_executor: CapabilityExecutor
    task_manager: TaskManager
    planner: Planner
    brain: Brain
    ui_context_projector: UIContextProjector
    agent_registry: AgentRegistry
    agent_resolver: AgentResolver
    agent_orchestrator: AgentOrchestrator

    autonomous_runtime: "AutonomousRuntime | None" = None

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def build_default_runtime(
    *,
    ollama_transport: OllamaTransport | None = None,
    comfyui_transport: ComfyUITransport | None = None,
    load_modules: bool = True,
    discover_ollama_models: bool = True,
    discover_comfyui_models: bool = True,
    discover_local_speech_models: bool = True,
    data_directory: Path | None = None,
    workspace_permission_prompt: WorkspacePermissionPrompt | None = None,
    sync_pool=None,  # PostgreSQL sync pool from CoreExecutionOwner
) -> ParikaRuntime:
    """
    Construct the default PARIKA runtime.

    Wires every Core component in the order mandated by
    `PARIKA_Architecture_Specification_v1.0.md` section 5.1, then
    registers and loads the Web Search, Runtime Info, Filesystem,
    Weather, Currency, News, and Chat Modules, and the Ollama
    Provider. Ollama connectivity failures during model
    discovery/health refresh are caught and logged rather than
    raised, so PARIKA remains usable (slash commands, and any
    already-available Tool-backed capability) even when Ollama is not
    installed or not running.

    Args:
        ollama_transport:
            Optional `OllamaTransport` override, primarily for tests.
            Defaults to `UrllibOllamaTransport`.

        load_modules:
            Whether to load (start) every registered Module
            immediately. Disable only for tests that want to control
            module loading themselves.

        discover_ollama_models:
            Whether to attempt Ollama model discovery and a health
            check immediately. Disable for tests/offline environments
            that want to skip the network round trip entirely.

        comfyui_transport:
            Optional `ComfyUITransport` override, primarily for tests.
            Defaults to `UrllibComfyUITransport`.

        discover_comfyui_models:
            Whether to attempt ComfyUI model discovery and a health
            check immediately. Disable for tests/offline environments
            that want to skip the network round trip entirely.

        discover_local_speech_models:
            Whether to attempt Local Speech provider model discovery
            immediately (a fast, local-only check for whether
            `faster-whisper`/Kokoro model files are
            installed -- never a network call). Disable only for
            tests that want to control this themselves.

        data_directory:
            Optional override for where the data directory is located.
            Defaults to `Configuration.get_project_root() /
            [data].directory` (normally the real project's `data/`
            directory), matching every existing caller's behavior.
            Tests that want an isolated, disposable runtime (so
            permanent Memory/Knowledge/Experience state never
            accumulates in the real project directory across test
            runs) should pass a `tmp_path`-derived directory here.

        workspace_permission_prompt:
            Optional `WorkspacePermissionPrompt` implementation, used
            by the shared `WorkspacePermissionManager` to interactively
            ask for a permission decision (Allow once/session/always/
            Deny) when the Filesystem or Shell Tool needs to touch a
            workspace outside the trusted set. `build_default_runtime()`
            deliberately has no Interface-specific default here - it
            is `None` unless the calling Interface supplies its own
            (e.g. the Console passes `CliWorkspacePermissionPrompt()`
            from `parika/console/app.py`), since prompting is
            inherently an Interface concern, not something this
            shared, Interface-agnostic builder should assume. With
            `None`, every request outside a trusted workspace fails
            closed (denied) rather than blocking.

        sync_pool:
            Optional PostgreSQL sync connection pool from CoreExecutionOwner.
            If provided, PostgreSQL storage implementations will use this pool.
            If not provided, test environment must provide PARIKA_TEST_DATABASE__* variables.

    Returns:
        A fully wired `ParikaRuntime`.
    """

    configuration = Configuration()
    configuration.load()

    resolved_data_directory = (
        data_directory
        if data_directory is not None
        else configuration.get_project_root() / configuration.get("data.directory", "data")
    )

    # Store data_directory override in configuration for API dependency to use
    if data_directory is not None:
        configuration._data_directory_override = str(resolved_data_directory)

    # Load database configuration
    db_config = load_database_config(configuration)
    
    # PostgreSQL is required
    if not db_config.enabled:
        raise RuntimeError("PostgreSQL is required but database.enabled is false in configuration")
    if sync_pool is None:
        # Create a default test pool for tests that don't provide one
        from parika.core.database.config import DatabaseConfig
        from parika.core.database.pool import PoolManager
        import os
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
        test_db_config = DatabaseConfig(
            enabled=True,
            host=test_host,
            port=test_port,
            database=test_database,
            username=test_username,
            password=test_password,
            pool_min_size=1,
            pool_max_size=10,
            connect_timeout=10.0,
            statement_timeout=0.0,
            application_name="parika_test",
            sslmode="disable",
        )
        sync_pool = PoolManager.initialize_sync_pool(test_db_config)
        # Mark that we own this pool so we can clean it up
        _owns_sync_pool = True
    else:
        _owns_sync_pool = False

    logger = Logger(configuration)
    event_bus = EventBus(logger)
    service_container = ServiceContainer()

    state_manager = StateManager(logger)
    resource_manager = ResourceManager(configuration=configuration, logger=logger)
    health_manager = HealthManager(event_bus=event_bus, logger=logger)
    metrics_manager = MetricsManager()

    context_manager = ContextManager(event_bus=event_bus, logger=logger)

    capability_registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
    capability_resolver = CapabilityResolver(
        capability_registry=capability_registry,
        logger=logger,
    )
    policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)

    permission_manager = PermissionManager(event_bus=event_bus, logger=logger)
    trust_writer = RuntimeTrustWriter(
        runtime_toml_path=configuration.get_project_root() / "config" / "runtime.toml",
        logger=logger,
    )
    workspace_permissions = WorkspacePermissionManager(
        permission_manager=permission_manager,
        configuration=configuration,
        event_bus=event_bus,
        logger=logger,
        prompt=workspace_permission_prompt,
        trust_writer=trust_writer,
    )

    memory_manager, knowledge_manager, experience_store = (
        _build_intelligence_foundation_stores(
            configuration=configuration,
            event_bus=event_bus,
            logger=logger,
            data_directory=resolved_data_directory,
            sync_pool=sync_pool,
        )
    )

    provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
    tool_manager = ToolManager(event_bus=event_bus, logger=logger)
    module_manager = ModuleManager(
        configuration=configuration,
        event_bus=event_bus,
        logger=logger,
    )
    # Expense Management's `ExpenseService` (and the `ExpenseStorage`/
    # PostgreSQL connection it owns) is constructed here, at the
    # composition root, for the same reason `tts_operation_registry`
    # below is: it is shared between `ExpenseModuleDriver`'s Tools
    # (the natural-language/Planner path) and the direct
    # `/api/v1/expenses...` handlers (the Web Client's structured CRUD
    # path) via `ServiceContainer` -- one shared data path, never two.
    expense_config = load_expense_config(configuration)
    expense_storage = PostgreSQLExpenseStorage(sync_pool)
    expense_storage.initialize()
    expense_service = ExpenseService(
        storage=expense_storage,
        event_bus=event_bus,
        logger=logger,
        config=expense_config,
    )

    # `MediaStateStore`/`MediaConnectionRegistry` are constructed here,
    # at the composition root, for the same reason
    # `tts_operation_registry` below is: they are shared between
    # `MediaModuleDriver`'s Tools (the natural-language/Planner path)
    # and the Media API/WebSocket layer (the Web Client's direct
    # path, `parika/api/ws/media.py`/`parika/api/routers/media.py`)
    # via `ServiceContainer` -- one shared state/transport, never two.
    media_state_store = MediaStateStore(event_bus=event_bus)
    media_connection_registry = MediaConnectionRegistry()

    tts_operation_registry = TtsOperationRegistry()
    # Seeded from `[voice].input_language` here (the
    # composition root) rather than inside `VoiceModuleDriver`, since
    # this instance is shared with the Voice API's settings endpoints
    # via `ServiceContainer` -- exactly like `tts_operation_registry`
    # above.
    _initial_voice_config = load_voice_config(configuration)
    voice_language_preference = VoiceLanguagePreferenceStore(
        default=VoiceLanguagePreference(
            input_language=_initial_voice_config.input_language,
        )
    )

    capability_executor = CapabilityExecutor(
        event_bus=event_bus,
        logger=logger,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
        configuration=configuration,
    )
    task_manager = TaskManager(
        event_bus=event_bus,
        logger=logger,
        capability_executor=capability_executor,
    )

    planner = Planner(
        capability_resolver=capability_resolver,
        resource_manager=resource_manager,
        policy_engine=policy_engine,
        provider_manager=provider_manager,
        tool_manager=tool_manager,
        logger=logger,
        configuration=configuration,
        experience_source=experience_store,
    )

    ui_context_projector = UIContextProjector(
        event_bus=event_bus,
        logger=logger,
        task_manager=task_manager,
        workflow_engine=module_manager,  # ModuleManager has workflow_engine access
        context_manager=context_manager,
        state_manager=state_manager,
        capability_registry=capability_registry,
    )
    ui_context_projector.start()

    # Agent Orchestrator - Multi-agent foundation (created after module loading)
    agent_registry = AgentRegistry(event_bus=event_bus, logger=logger)
    agent_resolver = AgentResolver(
        agent_registry=agent_registry,
        capability_registry=capability_registry,
        logger=logger,
    )
    agent_orchestrator = AgentOrchestrator(
        planner=planner,
        task_manager=task_manager,
        agent_registry=agent_registry,
        agent_resolver=agent_resolver,
        capability_registry=capability_registry,
        logger=logger,
        event_bus=event_bus,
    )

    brain = Brain(
        planner=planner,
        task_manager=task_manager,
        logger=logger,
        event_bus=event_bus,
        memory_manager=memory_manager,
        knowledge_manager=knowledge_manager,
        experience_source=experience_store,
        configuration=configuration,
        agent_orchestrator=agent_orchestrator,
    )

    # Set Brain reference on UI Context Projector for real execution state
    ui_context_projector.set_brain(brain)

    for service_type, instance in (
        (Configuration, configuration),
        (Logger, logger),
        (EventBus, event_bus),
        (StateManager, state_manager),
        (ResourceManager, resource_manager),
        (HealthManager, health_manager),
        (MetricsManager, metrics_manager),
        (ContextManager, context_manager),
        (CapabilityRegistry, capability_registry),
        (CapabilityResolver, capability_resolver),
        (PolicyEngine, policy_engine),
        (PermissionManager, permission_manager),
        (WorkspacePermissionManager, workspace_permissions),
        (MemoryManager, memory_manager),
        (KnowledgeManager, knowledge_manager),
        (ProviderManager, provider_manager),
        (ToolManager, tool_manager),
        (ModuleManager, module_manager),
        (TtsOperationRegistry, tts_operation_registry),
        (MediaStateStore, media_state_store),
        (MediaConnectionRegistry, media_connection_registry),
        (VoiceLanguagePreferenceStore, voice_language_preference),
        (ExpenseService, expense_service),
        (CapabilityExecutor, capability_executor),
        (TaskManager, task_manager),
        (Planner, planner),
        (Brain, brain),
        (UIContextProjector, ui_context_projector),
        (AgentRegistry, agent_registry),
        (AgentResolver, agent_resolver),
        (AgentOrchestrator, agent_orchestrator),
    ):
        service_container.register(service_type, instance)

    _register_modules(
        configuration=configuration,
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        module_manager=module_manager,
        health_manager=health_manager,
        memory_manager=memory_manager,
        knowledge_manager=knowledge_manager,
        event_bus=event_bus,
        experience_store=experience_store,
        tts_operation_registry=tts_operation_registry,
        voice_language_preference=voice_language_preference,
        expense_service=expense_service,
        media_state_store=media_state_store,
        media_connection_registry=media_connection_registry,
        logger=logger,
        load_modules=load_modules,
        data_directory=resolved_data_directory,
        workspace_permissions=workspace_permissions,
        brain=brain,
        sync_pool=sync_pool,
        service_container=service_container,
    )

    _register_ollama_provider(
        configuration=configuration,
        provider_manager=provider_manager,
        brain=brain,
        logger=logger,
        transport=ollama_transport,
        discover_models=discover_ollama_models,
    )

    _register_openai_compatible_providers(
        configuration=configuration, provider_manager=provider_manager,
        logger=logger, brain=brain, discover_models=discover_ollama_models,
    )

    _register_comfyui_provider(
        configuration=configuration,
        provider_manager=provider_manager,
        brain=brain,
        logger=logger,
        transport=comfyui_transport,
        discover_models=discover_comfyui_models,
    )

    _register_local_speech_provider(
        configuration=configuration,
        provider_manager=provider_manager,
        logger=logger,
        discover_models=discover_local_speech_models,
    )

    # Register initial agents AFTER modules are loaded and capabilities are registered
    _register_initial_agents(
        agent_registry=agent_registry,
        capability_registry=capability_registry,
        logger=logger,
    )

    return ParikaRuntime(
        configuration=configuration,
        logger=logger,
        event_bus=event_bus,
        service_container=service_container,
        state_manager=state_manager,
        resource_manager=resource_manager,
        health_manager=health_manager,
        metrics_manager=metrics_manager,
        context_manager=context_manager,
        capability_registry=capability_registry,
        capability_resolver=capability_resolver,
        policy_engine=policy_engine,
        permission_manager=permission_manager,
        workspace_permissions=workspace_permissions,
        memory_manager=memory_manager,
        knowledge_manager=knowledge_manager,
        provider_manager=provider_manager,
        tool_manager=tool_manager,
        module_manager=module_manager,
        capability_executor=capability_executor,
        task_manager=task_manager,
        planner=planner,
        brain=brain,
        ui_context_projector=ui_context_projector,
        agent_registry=agent_registry,
        agent_resolver=agent_resolver,
        agent_orchestrator=agent_orchestrator,
    )


def _register_initial_agents(
    *,
    agent_registry: AgentRegistry,
    capability_registry: CapabilityRegistry,
    logger: Logger,
) -> None:
    """
    Register the initial agent profiles based on actual repository capabilities.
    
    Agents are derived from the existing module/capability structure,
    not invented. Each agent has a specialization that maps to
    meaningful domains of capabilities in the repository.
    """
    from parika.core.agent_orchestrator.agent_profile import AgentProfile
    from parika.core.agent_orchestrator.agent_specialization import AgentSpecialization
    from parika.core.capability_registry.capability_category import CapabilityCategory

    # Helper to check if capability exists
    def has_cap(cap_id: str) -> bool:
        return capability_registry.contains(cap_id)

    # 1. General Agent - Fallback for chat.respond and general conversational LLM tasks
    general_caps = frozenset({
        "chat.respond",
    })
    general_allowed = frozenset({
        "chat.respond",
    })
    general_categories = frozenset({CapabilityCategory.LLM})
    
    agent_registry.register(AgentProfile(
        id="agent.general",
        name="General Agent",
        specialization=AgentSpecialization.GENERAL,
        preferred_capabilities=general_caps,
        allowed_capabilities=general_allowed,
        preferred_categories=general_categories,
        allowed_categories=general_categories,
        delegation_policy="allow",
        metadata={"description": "Handles general conversational LLM tasks (chat.respond)"},
    ))

    # 2. Coding Agent - Software engineering specialization
    coding_caps = frozenset({
        "coding.execute_task",
        "coding.plan_change",
    })
    coding_allowed = frozenset({
        "coding.execute_task",
        "coding.plan_change",
        "coding.parse",
        "coding.symbols",
        "coding.search",
        "coding.references",
        "coding.call_hierarchy",
        "coding.imports",
        "coding.dependencies",
        "coding.rename_plan",
        "coding.refactor_plan",
        "coding.patch_generate",
        "coding.document",
        "coding.format",
        "coding.lint",
        "coding.complexity",
        "coding.duplicates",
        "coding.dead_code",
        "coding.project_summary",
        "coding.graph_query",
        "coding.impact_analysis",
        "filesystem.read",
        "filesystem.write",
        "filesystem.list",
        "shell.execute",
        "web.search",
    })
    coding_categories = frozenset({
        CapabilityCategory.LLM,
        CapabilityCategory.TOOL,
    })
    
    agent_registry.register(AgentProfile(
        id="agent.coding",
        name="Coding Agent",
        specialization=AgentSpecialization.CODING,
        preferred_capabilities=coding_caps,
        allowed_capabilities=coding_allowed,
        preferred_categories=coding_categories,
        allowed_categories=coding_categories,
        preferred_models=frozenset({"codellama", "deepseek-coder", "qwen2.5-coder"}),
        behavioral_policies=MappingProxyType({
            "reasoning_depth": "deep",
            "tool_calling_style": "structured",
            "code_review_enabled": True,
        }),
        delegation_policy="allow",
        metadata={"description": "Specialized for software engineering tasks"},
    ))

    # 3. Research Agent - Information gathering
    research_caps = frozenset()
    research_allowed = frozenset()
    research_categories = frozenset({CapabilityCategory.TOOL})
    
    # Add available research capabilities
    if has_cap("web.search"):
        research_caps = frozenset({"web.search"})
        research_allowed = frozenset({"web.search"})
    if has_cap("news.latest"):
        research_caps = research_caps.union({"news.latest", "news.search", "news.topic"})
        research_allowed = research_allowed.union({"news.latest", "news.search", "news.topic"})
    if has_cap("knowledge.search"):  # Not a capability but shows intent
        pass
    
    if research_caps or has_cap("web.search") or has_cap("news.latest"):
        agent_registry.register(AgentProfile(
            id="agent.research",
            name="Research Agent",
            specialization=AgentSpecialization.RESEARCH,
            preferred_capabilities=research_caps,
            allowed_capabilities=research_allowed.union({
                "filesystem.read",
                "filesystem.list",
                "memory.search",
                "knowledge.search",
            }),
            preferred_categories=research_categories,
            allowed_categories=frozenset({CapabilityCategory.TOOL, CapabilityCategory.KNOWLEDGE, CapabilityCategory.MEMORY}),
            behavioral_policies=MappingProxyType({
                "reasoning_depth": "deep",
                "source_verification": True,
                "citation_style": "inline",
            }),
            delegation_policy="allow",
            metadata={"description": "Specialized for information gathering and research tasks"},
        ))

    # 4. Media Agent - Media playback/control
    media_caps = frozenset()
    media_allowed = frozenset()
    media_categories = frozenset({CapabilityCategory.TOOL})
    
    media_cap_ids = [
        "media.play", "media.pause", "media.resume", "media.stop",
        "media.skip", "media.previous", "media.seek", "media.set_volume",
        "media.mute", "media.unmute", "media.show", "media.hide", "media.get_state",
    ]
    for cap in media_cap_ids:
        if has_cap(cap):
            media_caps = media_caps.union({cap})
            media_allowed = media_allowed.union({cap})
    
    if media_caps:
        agent_registry.register(AgentProfile(
            id="agent.media",
            name="Media Agent",
            specialization=AgentSpecialization.MEDIA,
            preferred_capabilities=media_caps,
            allowed_capabilities=media_allowed.union({"web.search"}),
            preferred_categories=media_categories,
            allowed_categories=frozenset({CapabilityCategory.TOOL, CapabilityCategory.NETWORK}),
            behavioral_policies=MappingProxyType({
                "response_style": "concise",
                "queue_management": True,
            }),
            delegation_policy="allow",
            metadata={"description": "Specialized for media playback and control"},
        ))

    # 5. System Agent - Utilities (filesystem, shell, weather, currency, expense, runtime)
    system_caps = frozenset()
    system_allowed = frozenset()
    system_categories = frozenset({CapabilityCategory.TOOL})
    
    system_cap_ids = [
        "filesystem.read", "filesystem.write", "filesystem.list",
        "filesystem.search", "filesystem.walk", "filesystem.copy",
        "filesystem.move", "filesystem.delete", "filesystem.mkdir",
        "filesystem.exists", "filesystem.info", "filesystem.permissions",
        "filesystem.watch",
        "shell.execute",
        "weather.current", "weather.forecast",
        "currency.exchange_rate", "currency.convert",
        "expense.add", "expense.get", "expense.list", "expense.update", "expense.remove", "expense.summarize", "expense.compare",
        "runtime.info",
    ]
    for cap in system_cap_ids:
        if has_cap(cap):
            system_caps = system_caps.union({cap})
            system_allowed = system_allowed.union({cap})
    
    if system_caps:
        agent_registry.register(AgentProfile(
            id="agent.system",
            name="System Agent",
            specialization=AgentSpecialization.SYSTEM,
            preferred_capabilities=system_caps,
            allowed_capabilities=system_allowed.union({"web.search", "filesystem.read", "filesystem.list"}),
            preferred_categories=system_categories,
            allowed_categories=frozenset({CapabilityCategory.TOOL, CapabilityCategory.FILESYSTEM, CapabilityCategory.NETWORK, CapabilityCategory.SYSTEM}),
            behavioral_policies=MappingProxyType({
                "response_style": "concise",
                "safety_first": True,
            }),
            delegation_policy="allow",
            metadata={"description": "Handles system utilities and general tool operations"},
        ))

    # 6. Vision Agent - Visual/multimedia capabilities
    vision_caps = frozenset()
    vision_allowed = frozenset()
    vision_categories = frozenset({CapabilityCategory.VISION, CapabilityCategory.OCR, CapabilityCategory.IMAGE_GENERATION, CapabilityCategory.VIDEO_GENERATION})
    
    vision_cap_ids = [
        "vision.describe_image", "vision.detect_objects", "vision.compare_images",
        "ocr.extract_text", "ocr.provider_extract_text",
        "document.read_pdf", "document.extract_text",
        "video.generate", "video.edit",
        "image.generate", "image.edit",
    ]
    for cap in vision_cap_ids:
        if has_cap(cap):
            vision_caps = vision_caps.union({cap})
            vision_allowed = vision_allowed.union({cap})
    
    # Add wildcard patterns for provider capabilities (vision, image, video generation)
    # These use the '*' suffix supported by AgentProfile.can_use_capability()
    vision_allowed = vision_allowed.union({
        "vision.provider_*",
        "image.provider_*",
        "video.provider_*",
    })
    
    if vision_caps:
        agent_registry.register(AgentProfile(
            id="agent.vision",
            name="Vision Agent",
            specialization=AgentSpecialization.VISION,
            preferred_capabilities=vision_caps,
            allowed_capabilities=vision_allowed.union({"filesystem.read", "web.search"}),
            preferred_categories=vision_categories,
            allowed_categories=frozenset({CapabilityCategory.VISION, CapabilityCategory.OCR, CapabilityCategory.IMAGE_GENERATION, CapabilityCategory.VIDEO_GENERATION, CapabilityCategory.TOOL, CapabilityCategory.FILESYSTEM}),
            preferred_models=frozenset({"llava", "bakllava", "moondream"}),
            behavioral_policies=MappingProxyType({
                "detail_level": "comprehensive",
                "visual_reasoning": True,
            }),
            delegation_policy="allow",
            metadata={"description": "Specialized for visual understanding and generation tasks"},
        ))

    # 7. Voice Agent - Speech-to-text and text-to-speech provider capabilities
    voice_caps = frozenset()
    voice_allowed = frozenset()
    voice_categories = frozenset({CapabilityCategory.SPEECH, CapabilityCategory.TEXT_TO_SPEECH})
    
    voice_cap_ids = [
        "voice.provider_speech_to_text",
        "voice.provider_text_to_speech",
    ]
    for cap in voice_cap_ids:
        if has_cap(cap):
            voice_caps = voice_caps.union({cap})
            voice_allowed = voice_allowed.union({cap})
    
    if voice_caps:
        agent_registry.register(AgentProfile(
            id="agent.voice",
            name="Voice Agent",
            specialization=AgentSpecialization.VOICE,
            preferred_capabilities=voice_caps,
            allowed_capabilities=voice_allowed.union({"filesystem.read", "web.search"}),
            preferred_categories=voice_categories,
            allowed_categories=frozenset({CapabilityCategory.SPEECH, CapabilityCategory.TEXT_TO_SPEECH, CapabilityCategory.TOOL, CapabilityCategory.FILESYSTEM}),
            behavioral_policies=MappingProxyType({
                "response_style": "concise",
                "audio_processing": True,
            }),
            delegation_policy="allow",
            metadata={"description": "Specialized for speech recognition and synthesis tasks"},
        ))

    # Use module-level logger for this message
    import logging
    logging.getLogger("parika").info("Registered initial agent profiles based on available capabilities")


def shutdown_runtime(runtime: ParikaRuntime) -> None:
    """
    Gracefully unload every active Module.

    Args:
        runtime:
            Runtime previously produced by `build_default_runtime()`.
    """

    runtime.ui_context_projector.stop()
    runtime.module_manager.unload_all()
    runtime.memory_manager.shutdown()
    
    # Shutdown Autonomous Runtime if it was started
    if runtime.autonomous_runtime is not None:
        try:
            import asyncio
            asyncio.run(runtime.autonomous_runtime.stop())
        except Exception as e:
            runtime.logger.get_logger(__name__).error("Error shutting down Autonomous Runtime: %s", e)


def _build_intelligence_foundation_stores(
    *,
    configuration: Configuration,
    event_bus: EventBus,
    logger: Logger,
    data_directory: Path,
    sync_pool,  # PostgreSQL sync pool (required)
) -> tuple[MemoryManager, KnowledgeManager, ExperienceStore]:
    """
    Construct and initialize MemoryManager, KnowledgeManager (with its
    PostgreSQL source storage), and ExperienceStore -- in that order, all
    before Planner/Brain are constructed, since both need them ready
    (Planner needs `experience_store` for its optional
    `experience_source`; Brain needs `memory_manager`/
    `knowledge_manager` for `assemble_context()`).

    ExperienceStore is a Module-owned object, not Core -- see
    docs/architecture/Intelligence_Foundation_Design.md section 6A --
    but is still materialized here at the composition root, exactly
    like MemoryManager/PostgreSQLKnowledgeStorage, for the same readiness
    reason. Planner only ever receives it through the structurally-
    typed `ExperienceSource` Protocol it owns; `planner.py` never
    imports this class.
    """

    from parika.core.memory_manager.postgresql_storage import PostgreSQLMemoryStorage
    from parika.core.knowledge_manager.postgresql_storage import PostgreSQLKnowledgeStorage
    from parika.modules.experience.postgresql_storage import PostgreSQLExperienceStorage

    memory_storage = PostgreSQLMemoryStorage(sync_pool)
    memory_storage.initialize()
    memory_manager = MemoryManager(
        logger=logger,
        event_bus=event_bus,
        storage=memory_storage,
        configuration=configuration,
    )

    knowledge_storage = PostgreSQLKnowledgeStorage(sync_pool)
    knowledge_storage.initialize()
    knowledge_manager = KnowledgeManager(
        storage=knowledge_storage,
        registry=KnowledgeEngineRegistry(),
        event_bus=event_bus,
        logger=logger,
    )

    experience_store = ExperienceStore(
        logger=logger,
        storage=PostgreSQLExperienceStorage(sync_pool),
    )
    experience_store.initialize()

    return memory_manager, knowledge_manager, experience_store


def _register_modules(
    *,
    configuration: Configuration,
    capability_registry: CapabilityRegistry,
    tool_manager: ToolManager,
    module_manager: ModuleManager,
    health_manager: HealthManager,
    memory_manager: MemoryManager,
    knowledge_manager: KnowledgeManager,
    event_bus: EventBus,
    experience_store: ExperienceStore,
    tts_operation_registry: TtsOperationRegistry,
    voice_language_preference: VoiceLanguagePreferenceStore,
    expense_service: ExpenseService,
    media_state_store: MediaStateStore,
    media_connection_registry: MediaConnectionRegistry,
    logger: Logger,
    load_modules: bool,
    data_directory: Path,
    workspace_permissions: WorkspacePermissionManager,
    brain: Brain,
    sync_pool,  # PostgreSQL sync pool
    service_container: ServiceContainer,
) -> None:
    """
    Register the built-in Web Search, Runtime Info, Filesystem, Shell,
    Weather, Currency, News, Expense Management, Chat, Coding,
    Repository Intelligence, Coding Agent, OCR, and Vision Modules,
    and optionally load them immediately.

    Coding, Repository Intelligence, and Coding Agent are registered
    in that exact dependency order (see
    docs/development/Module_Guide.md
    section 14): Coding constructs `CodingIndexStorage`/
    `LanguageAnalyzerRegistry` first; Repository Intelligence receives
    those same instances; Coding Agent receives the already-
    constructed `Brain`.

    OCR (`ocr.extract_text`/`ocr.provider_extract_text`, §18.4) and
    Vision (`vision.*`, §18.5) are registered last, after Coding Agent,
    purely by convention (they mirror Coding Agent's own
    two-Capability shape most closely); neither has a construction-
    order dependency on any other Module, since both only ever reach
    `filesystem.read` through an ordinary nested `Goal`/`Brain.handle()`
    call at request time, never at registration time.
    """

    web_search_driver = WebSearchModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_web_search_module(web_search_driver))

    autonomous_driver = load_autonomous_module(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
        pool_manager=sync_pool,
        event_bus=event_bus,
    )
    module_manager.register(create_autonomous_module(autonomous_driver))

    runtime_info_driver = RuntimeInfoModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
    )
    module_manager.register(create_runtime_info_module(runtime_info_driver))

    filesystem_driver = FilesystemModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
        configuration=configuration,
        permissions=workspace_permissions,
    )
    module_manager.register(create_filesystem_module(filesystem_driver))

    shell_driver = ShellModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        permissions=workspace_permissions,
        logger=logger,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_shell_module(shell_driver))

    weather_driver = WeatherModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_weather_module(weather_driver))

    currency_driver = CurrencyModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_currency_module(currency_driver))

    news_driver = NewsModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_news_module(news_driver))

    expense_driver = ExpenseModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        service=expense_service,
        logger=logger,
        health_manager=health_manager,
    )
    module_manager.register(create_expense_module(expense_driver))

    chat_driver = ChatModuleDriver(
        capability_registry=capability_registry,
        logger=logger,
        health_manager=health_manager,
    )
    module_manager.register(create_chat_module(chat_driver))

    knowledge_indexing_driver = KnowledgeIndexingModuleDriver(
        knowledge_manager=knowledge_manager,
        logger=logger,
        database_path=sync_pool,  # PostgreSQL pool
        health_manager=health_manager,
    )
    module_manager.register(
        create_knowledge_indexing_module(knowledge_indexing_driver)
    )

    experience_driver = ExperienceModuleDriver(
        experience_store=experience_store,
        event_bus=event_bus,
        health_manager=health_manager,
    )
    module_manager.register(create_experience_module(experience_driver))

    memory_module_driver = MemoryModuleDriver(
        memory_manager=memory_manager,
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_memory_module(memory_module_driver))

    # --- Developer Intelligence Platform: Coding, Repository
    # Intelligence, Coding Agent -- registered in dependency order
    # (see this function's own docstring). ---

    coding_driver = CodingModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        database_path=sync_pool,  # PostgreSQL pool
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_coding_module(coding_driver))

    repository_intelligence_driver = RepositoryIntelligenceModuleDriver(
        knowledge_manager=knowledge_manager,
        coding_storage=coding_driver.storage,
        analyzer_registry=coding_driver.registry,
        max_file_size_bytes=coding_driver.max_file_size_bytes,
        tool_manager=tool_manager,
        logger=logger,
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(
        create_repository_intelligence_module(repository_intelligence_driver)
    )

    default_workspace = _resolve_default_workspace(configuration)
    coding_agent_driver = CodingAgentModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        default_workspace=default_workspace,
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_coding_agent_module(coding_agent_driver))

    ocr_driver = OcrModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_ocr_module(ocr_driver))

    vision_driver = VisionModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_vision_module(vision_driver))

    # Document Module: PARIKA's single entry point for document
    # processing. Registered after OCR since it reuses OCR's own
    # `ocr.extract_text` Capability for scanned/image-only PDFs --
    # though, as with OCR/Vision, this ordering has no construction-
    # time dependency: nested Goal resolution is entirely dynamic, at
    # request time, after every Module has already loaded.
    document_driver = DocumentModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_document_module(document_driver))

    # Video Module: builds on top of OCR/Vision/Document rather than
    # duplicating any of their implementations. Registered last, after
    # OCR/Vision/Document, since it reuses their own Provider
    # Capabilities directly (`vision.provider_describe_image`,
    # `vision.provider_detect_objects`, `ocr.provider_extract_text`) --
    # though, exactly like every other Module here, this ordering has
    # no construction-time dependency: nested Goal resolution is
    # entirely dynamic, at request time, after every Module has
    # already loaded.
    video_driver = VideoModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_video_module(video_driver))

    # Generation Module: registers `image.generate`/`image.edit`/
    # `video.generate`/`video.generate_from_image`/`video.edit`.
    # Registered last, after every understanding-focused Module,
    # since it is a distinct generation-vs-understanding concern (see
    # its own manifest docstring) with no construction-time dependency
    # on any other Module -- its Provider Capabilities are resolved
    # dynamically, at request time, by Planner's Model Selection
    # Framework, exactly like every other Module here.
    generation_driver = GenerationModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_generation_module(generation_driver))

    # Voice Module: registers `voice.speech_to_text`/
    # `voice.text_to_speech`. Registered last, after Generation, for
    # the same "no construction-time dependency on any other Module"
    # reason -- its Provider Capabilities are resolved dynamically, at
    # request time, by Planner's Model Selection Framework, exactly
    # like every other Module here. Shares one `TtsOperationRegistry`
    # with the Voice API's `/voice/speak/{operation_id}/stop` handler
    # (see `parika/api/handlers/voice.py`), both reading it from
    # `ServiceContainer`.
    voice_driver = VoiceModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        operation_registry=tts_operation_registry,
        language_preference=voice_language_preference,
        event_bus=event_bus,
        health_manager=health_manager,
        configuration=configuration,
    )
    module_manager.register(create_voice_module(voice_driver))
    # Register the driver in ServiceContainer so API handlers can access
    # the TextToSpeechToolDriver directly for streaming synthesis.
    service_container.register(VoiceModuleDriver, voice_driver)

    # Media Module: registers `media.play`/`media.pause`/.../
    # `media.get_state`. Registered last, after Voice, for the same
    # "no construction-time dependency on any other Module" reason --
    # its free-text `media.play` resolution reaches the existing
    # `web.search` Capability dynamically, at request time, through an
    # ordinary nested Goal/`Brain.handle()` call, exactly like every
    # other Module here. Shares `MediaStateStore`/
    # `MediaConnectionRegistry` with the Media API/WebSocket layer
    # (`parika/api/routers/media.py`/`parika/api/ws/media.py`), both
    # reading them from `ServiceContainer`. See
    # `docs/architecture/adr/0004-media-capability.md`.
    media_config = load_media_config(configuration)
    media_path_security = LocalMediaPathSecurity(
        LocalMediaPathSecurityConfig(
            allowed_roots=tuple(Path(root) for root in media_config.allowed_local_roots)
        )
    )
    media_resolver = MediaResolver(
        path_security=media_path_security,
        brain=brain if media_config.youtube_search_enabled else None,
    )
    media_driver = MediaModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        state_store=media_state_store,
        dispatcher=media_connection_registry,
        resolver=media_resolver,
        config=media_config,
        logger=logger,
        health_manager=health_manager,
    )
    module_manager.register(create_media_module(media_driver))

    if not load_modules:
        return

    module_manager.load(WEB_SEARCH_MODULE_ID)
    module_manager.load(RUNTIME_INFO_MODULE_ID)
    module_manager.load(FILESYSTEM_MODULE_ID)
    module_manager.load(SHELL_MODULE_ID)
    module_manager.load(WEATHER_MODULE_ID)
    module_manager.load(CURRENCY_MODULE_ID)
    module_manager.load(NEWS_MODULE_ID)
    module_manager.load(EXPENSE_MODULE_ID)
    module_manager.load(CHAT_MODULE_ID)

    # Coding, then Repository Intelligence, load and therefore
    # register their KnowledgeEngine (RepositoryKnowledgeEngine) with
    # KnowledgeManager BEFORE Knowledge Indexing registers its own
    # CodeKnowledgeEngine. Both engines declare `supports()` for the
    # same REPOSITORY/WORKSPACE source kinds, and
    # `KnowledgeEngineRegistry.resolve()` is a first-match registry
    # (frozen, unmodified Core behavior) - registering the richer,
    # superseding engine first is what makes it the one actually
    # resolved for those kinds, exactly as
    # docs/development/Module_Guide.md
    # section 7.4 intends. `CodeKnowledgeEngine` remains registered,
    # unmodified, and still correctly reports `supports()=True` in
    # isolation (its own unit tests are unaffected); this ordering
    # only decides which engine actually serves a REPOSITORY/WORKSPACE
    # source when both are registered together, in this one runtime.
    module_manager.load(CODING_MODULE_ID)
    module_manager.load(REPOSITORY_INTELLIGENCE_MODULE_ID)

    module_manager.load(KNOWLEDGE_INDEXING_MODULE_ID)
    module_manager.load(MEMORY_MODULE_ID)
    module_manager.load(EXPERIENCE_MODULE_ID)
    module_manager.load(CODING_AGENT_MODULE_ID)
    module_manager.load(OCR_MODULE_ID)
    module_manager.load(VISION_MODULE_ID)
    module_manager.load(DOCUMENT_MODULE_ID)
    module_manager.load(VIDEO_MODULE_ID)
    module_manager.load(GENERATION_MODULE_ID)
    module_manager.load(VOICE_MODULE_ID)
    module_manager.load(MEDIA_MODULE_ID)


def _resolve_default_workspace(configuration: Configuration) -> Path:
    """
    Resolve `[workspace].default_workspace`, mirroring
    `parika.tools.shell.config.load_shell_config()`'s own resolution
    -- used as the Coding Agent's default `workspace_root` when a
    caller omits one.
    """

    project_root = configuration.get_project_root()
    raw_default_workspace = configuration.get("workspace.default_workspace", "data")

    if not raw_default_workspace:
        return project_root

    default_workspace = Path(str(raw_default_workspace))

    if not default_workspace.is_absolute():
        default_workspace = project_root / default_workspace

    return default_workspace


def _register_ollama_provider(
    *,
    configuration: Configuration,
    provider_manager: ProviderManager,
    brain: Brain,
    logger: Logger,
    transport: OllamaTransport | None,
    discover_models: bool,
) -> None:
    """
    Register the Ollama provider and, on a best-effort basis, discover
    its installed models and refresh its health.

    Ollama connectivity failures are caught and logged rather than
    propagated, so a missing or offline Ollama installation never
    prevents PARIKA from starting.
    """

    log = logger.get_logger(__name__)

    if not configuration.get("providers.ollama.enabled", True):
        log.info("Ollama provider is disabled by configuration.")
        return

    driver = OllamaProviderDriver(
        transport=transport or UrllibOllamaTransport(),
        logger=logger,
        base_url=configuration.get(
            "providers.ollama.base_url",
            DEFAULT_BASE_URL,
        ),
        connect_timeout_seconds=configuration.get(
            "providers.ollama.connect_timeout_seconds",
            DEFAULT_CONNECT_TIMEOUT_SECONDS,
        ),
        request_timeout_seconds=configuration.get(
            "providers.ollama.request_timeout_seconds",
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
    )
    driver.bind_brain(brain)

    provider_manager.register(create_ollama_provider(), driver)

    if not discover_models:
        return

    try:
        provider_manager.discover_models(OLLAMA_PROVIDER_ID)
    except OllamaProviderError as ex:
        log.warning(
            "Could not discover Ollama models (%s). Ollama may not "
            "be installed or running; chat will be unavailable until "
            "it is.",
            ex,
        )
        return

    try:
        provider_manager.refresh_health(OLLAMA_PROVIDER_ID)
    except OllamaProviderError as ex:
        log.warning("Could not refresh Ollama health: %s", ex)


def _register_comfyui_provider(
    *,
    configuration: Configuration,
    provider_manager: ProviderManager,
    brain: Brain,
    logger: Logger,
    transport: ComfyUITransport | None,
    discover_models: bool,
) -> None:
    """
    Register the ComfyUI provider and, on a best-effort basis, discover
    its installed models and refresh its health.

    Mirrors `_register_ollama_provider()` exactly. `brain` is accepted
    for parity with that function's signature and in case a future
    ComfyUI capability needs it, but `ComfyUIProviderDriver` has no
    `bind_brain()` -- generation requests never resolve a tool call
    back through Brain the way Ollama's chat loop does.

    ComfyUI connectivity failures are caught and logged rather than
    propagated, so a missing or offline ComfyUI installation never
    prevents PARIKA from starting; `image.generate`/`image.edit`/
    `video.generate`/`video.generate_from_image`/`video.edit` simply
    remain unavailable (no compatible Provider model) until ComfyUI is
    reachable.
    """

    log = logger.get_logger(__name__)

    if not configuration.get("providers.comfyui.enabled", True):
        log.info("ComfyUI provider is disabled by configuration.")
        return

    model_config = ComfyUIModelConfig(
        image_diffusion_model=configuration.get(
            "providers.comfyui.image_diffusion_model",
            ComfyUIModelConfig().image_diffusion_model,
        ),
        image_text_encoder=configuration.get(
            "providers.comfyui.image_text_encoder",
            ComfyUIModelConfig().image_text_encoder,
        ),
        image_vae=configuration.get(
            "providers.comfyui.image_vae", ComfyUIModelConfig().image_vae
        ),
        video_t2v_diffusion_model=configuration.get(
            "providers.comfyui.video_t2v_diffusion_model",
            ComfyUIModelConfig().video_t2v_diffusion_model,
        ),
        video_t2v_loader=configuration.get(
            "providers.comfyui.video_t2v_loader",
            ComfyUIModelConfig().video_t2v_loader,
        ),
        video_t2v_weight_dtype=configuration.get(
            "providers.comfyui.video_t2v_weight_dtype",
            ComfyUIModelConfig().video_t2v_weight_dtype,
        ),
        video_vace_diffusion_model=configuration.get(
            "providers.comfyui.video_vace_diffusion_model",
            ComfyUIModelConfig().video_vace_diffusion_model,
        ),
        video_vace_loader=configuration.get(
            "providers.comfyui.video_vace_loader",
            ComfyUIModelConfig().video_vace_loader,
        ),
        video_vace_weight_dtype=configuration.get(
            "providers.comfyui.video_vace_weight_dtype",
            ComfyUIModelConfig().video_vace_weight_dtype,
        ),
        video_text_encoder=configuration.get(
            "providers.comfyui.video_text_encoder",
            ComfyUIModelConfig().video_text_encoder,
        ),
        video_vae=configuration.get(
            "providers.comfyui.video_vae", ComfyUIModelConfig().video_vae
        ),
    )

    driver = ComfyUIProviderDriver(
        transport=transport or UrllibComfyUITransport(),
        logger=logger,
        base_url=configuration.get(
            "providers.comfyui.base_url",
            COMFYUI_DEFAULT_BASE_URL,
        ),
        connect_timeout_seconds=configuration.get(
            "providers.comfyui.connect_timeout_seconds",
            COMFYUI_DEFAULT_CONNECT_TIMEOUT_SECONDS,
        ),
        request_timeout_seconds=configuration.get(
            "providers.comfyui.request_timeout_seconds",
            COMFYUI_DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
        poll_interval_seconds=configuration.get(
            "providers.comfyui.poll_interval_seconds",
            COMFYUI_DEFAULT_POLL_INTERVAL_SECONDS,
        ),
        poll_timeout_seconds=configuration.get(
            "providers.comfyui.poll_timeout_seconds",
            COMFYUI_DEFAULT_POLL_TIMEOUT_SECONDS,
        ),
        model_config=model_config,
    )

    provider_manager.register(create_comfyui_provider(), driver)

    if not discover_models:
        return

    try:
        provider_manager.discover_models(COMFYUI_PROVIDER_ID)
    except ComfyUIProviderError as ex:
        log.warning(
            "Could not discover ComfyUI models (%s). ComfyUI may not "
            "be installed or running; image/video generation will be "
            "unavailable until it is.",
            ex,
        )
        return

    try:
        provider_manager.refresh_health(COMFYUI_PROVIDER_ID)
    except ComfyUIProviderError as ex:
        log.warning("Could not refresh ComfyUI health: %s", ex)


def _register_local_speech_provider(
    *,
    configuration: Configuration,
    provider_manager: ProviderManager,
    logger: Logger,
    discover_models: bool,
) -> None:
    """
    Register the Local Speech provider and, on a best-effort basis,
    discover which of its two models (speech-to-text, text-to-speech)
    are actually installed/configured.

    Mirrors `_register_ollama_provider()`/`_register_comfyui_provider()`,
    except discovery here is a fast, local-only presence check (see
    `parika.providers.local_speech.discovery`) -- never a network
    call -- so failures are limited to "the optional dependency/model
    is simply not installed yet", caught and logged rather than
    propagated, exactly like a missing/offline ComfyUI or Ollama
    installation: `voice.speech_to_text`/`voice.text_to_speech` simply
    remain unavailable (no compatible Provider model) until the
    relevant engine is installed/configured.
    """

    log = logger.get_logger(__name__)

    if not configuration.get("providers.local_speech.enabled", True):
        log.info("Local Speech provider is disabled by configuration.")
        return

    config = load_local_speech_config(configuration)
    driver = LocalSpeechProviderDriver(config=config, logger=logger)

    provider_manager.register(create_local_speech_provider(), driver)

    if not discover_models:
        return

    try:
        provider_manager.discover_models(LOCAL_SPEECH_PROVIDER_ID)
    except LocalSpeechProviderError as ex:
        log.warning(
            "Could not discover Local Speech models (%s). Voice "
            "speech-to-text/text-to-speech will be unavailable until "
            "the relevant optional dependency/model is installed.",
            ex,
        )
        return

    try:
        provider_manager.refresh_health(LOCAL_SPEECH_PROVIDER_ID)
    except LocalSpeechProviderError as ex:
        log.warning("Could not refresh Local Speech health: %s", ex)


def _register_openai_compatible_providers(*, configuration, provider_manager,
                                           logger, brain, discover_models: bool) -> None:
    """Register every configured generic cloud provider instance."""
    log = logger.get_logger(__name__)
    for cfg in load_openai_compatible_configs(configuration):
        try:
            driver = OpenAICompatibleProviderDriver(
                provider_id=cfg.provider_id, base_url=cfg.base_url,
                model=cfg.model, api_key_env=cfg.api_key_env, logger=logger,
                transport=None, **cfg.options,
            )
            driver.bind_brain(brain)
            provider_manager.register(Provider(
                id=cfg.provider_id, name=cfg.provider_id,
                description="Configuration-driven OpenAI-compatible provider",
                metadata={"provider_type": "openai_compatible"},
            ), driver)
            if discover_models:
                provider_manager.discover_models(cfg.provider_id)
                provider_manager.refresh_health(cfg.provider_id)
        except OpenAICompatibleError as ex:
            log.warning("Could not register provider '%s': %s", cfg.provider_id, ex)
