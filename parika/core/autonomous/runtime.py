"""
PARIKA Autonomous Runtime Composition Root

Builds and wires the complete autonomous execution subsystem.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Optional

from psycopg_pool import ConnectionPool
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.service_container.service_container import ServiceContainer
from parika.core.configuration.configuration import Configuration
from parika.core.configuration.autonomous_config import load_autonomous_settings, AutonomousSettings
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.planner import Planner
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager

# Autonomous repositories
from parika.core.autonomous.repository import (
    MissionRepository,
    AutonomousTaskRepository,
    TaskDependencyRepository,
    AgentInstanceRepository,
    WorkerRepository,
    ExecutionRepository,
    CheckpointRepository,
    WorldStateRepository,
    AutonomousEventRepository,
    AgentMessageRepository,
)

# Autonomous managers
from parika.core.autonomous.mission_manager import MissionManager
from parika.core.autonomous.task_manager import AutonomousTaskManager
from parika.core.autonomous.worker_manager import WorkerManager
from parika.core.autonomous.checkpoint_manager import CheckpointManager
from parika.core.autonomous.recovery_coordinator import RecoveryCoordinator
from parika.core.autonomous.agent_supervisor import AgentSupervisor
from parika.core.autonomous.world_state_manager import WorldStateManager

# Autonomous authorization & budget
from parika.core.autonomous.authorization import AutonomousAuthorizationBoundary, create_autonomous_authorization_boundary
from parika.core.autonomous.budget import BudgetEnforcer

# Skill system
from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.skill_system.skill_catalog import SkillCatalog
from parika.core.skill_system.skill_loader import SkillLoader
from parika.core.skill_system.skill_security import SkillSecurityScanner

# Implementation system
from parika.core.implementation_registry.implementation_registry import ImplementationRegistry
from parika.core.implementation_registry.implementation_resolver import ImplementationResolver

# Agent runtime
from parika.core.agent_runtime.runtime_registry import RuntimeRegistry
from parika.core.agent_runtime.contracts import RuntimeConfig, RuntimeCapabilities, RuntimeType
from parika.core.agent_runtime.native_backend import NativeBackend
from parika.core.agent_runtime.hermes_backend import HermesBackend
from parika.core.agent_runtime.remote_backend import RemoteBackend

# Agent communication
from parika.core.agent_communication.message_bus import MessageBus
from parika.core.agent_communication.message_repository import AgentMessageRepository

# Multi-agent
from parika.core.multi_agent.mission_coordinator import MissionCoordinator
from parika.core.multi_agent.agent_selector import AgentSelector

# Autonomous waiting
from parika.core.autonomous_waiting.wait_manager import WaitManager

# New execution components
from parika.core.autonomous.execution_strategy_resolver import ExecutionStrategyResolver
from parika.core.autonomous.dispatcher import ExecutionDispatcher
from parika.core.autonomous.executor import AutonomousExecutor
from parika.core.autonomous.execution_backend import ExecutionBackend


class RuntimeLifecycleState(Enum):
    """Autonomous Runtime lifecycle states."""
    CONSTRUCTED = "constructed"
    STARTING = "starting"
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True, kw_only=True)
class AutonomousRuntime:
    """
    Complete autonomous runtime composition.
    
    Contains all services needed for autonomous mission/task/agent execution.
    """
    # Configuration
    settings: AutonomousSettings
    configuration: Configuration
    
    # Database
    sync_pool: ConnectionPool
    
    # Core infrastructure
    event_bus: EventBus
    logger: Logger
    service_container: ServiceContainer
    
    # Core services (injected from normal runtime)
    capability_resolver: CapabilityResolver
    planner: Planner
    capability_executor: CapabilityExecutor
    tool_manager: ToolManager
    provider_manager: ProviderManager
    resource_manager: ResourceManager
    policy_engine: PolicyEngine
    permission_manager: PermissionManager
    workspace_permission_manager: WorkspacePermissionManager
    
    # Repositories
    mission_repository: MissionRepository
    task_repository: AutonomousTaskRepository
    dependency_repository: TaskDependencyRepository
    agent_repository: AgentInstanceRepository
    worker_repository: WorkerRepository
    execution_repository: ExecutionRepository
    checkpoint_repository: CheckpointRepository
    world_state_repository: WorldStateRepository
    event_repository: AutonomousEventRepository
    message_repository: AgentMessageRepository
    
    # Managers
    mission_manager: MissionManager
    task_manager: AutonomousTaskManager
    worker_manager: WorkerManager
    checkpoint_manager: CheckpointManager
    recovery_coordinator: RecoveryCoordinator
    agent_supervisor: AgentSupervisor
    world_state_manager: WorldStateManager
    
    # Authorization & Budget
    authorization_boundary: AutonomousAuthorizationBoundary
    budget_enforcer: BudgetEnforcer
    
    # Skill system
    skill_registry: SkillRegistry
    skill_catalog: SkillCatalog
    skill_loader: SkillLoader
    security_scanner: SkillSecurityScanner
    
    # Implementation system
    implementation_registry: ImplementationRegistry
    implementation_resolver: ImplementationResolver
    
    # Runtime registry (availability tracker)
    runtime_registry: RuntimeRegistry
    
    # Execution backends
    native_backend: NativeBackend
    hermes_backend: HermesBackend | None
    remote_backend: RemoteBackend
    
    # Execution resolution and dispatch
    execution_strategy_resolver: ExecutionStrategyResolver
    dispatcher: ExecutionDispatcher
    
    # Agent communication
    message_bus: MessageBus
    wait_manager: WaitManager
    
    # Multi-agent
    mission_coordinator: MissionCoordinator
    agent_selector: AgentSelector
    
    # Autonomous waiting
    wait_manager_instance: WaitManager
    
    # Core executor
    executor: AutonomousExecutor
    
    # Lifecycle
    _lifecycle_state: RuntimeLifecycleState = field(default=RuntimeLifecycleState.CONSTRUCTED, init=False)
    _startup_exception: Optional[BaseException] = field(default=None, init=False)
    _started_components: list[str] = field(default_factory=list, init=False)
    
    async def start(self, *, auto_recover: bool = True) -> None:
        """
        Start the autonomous runtime.
        
        Starts components in dependency order:
        1. Recovery (if auto_recover)
        2. Executor (background thread)
        3. Message bus (async)
        4. Skill catalog initialization
        5. Hermes health check (if enabled)
        
        If any step fails, all previously started components are stopped
        in reverse order (rollback).
        
        Args:
            auto_recover: Whether to run recovery on startup
            
        Raises:
            RuntimeError: If already started or startup fails
        """
        if self._lifecycle_state == RuntimeLifecycleState.STARTED:
            return
        if self._lifecycle_state == RuntimeLifecycleState.STARTING:
            raise RuntimeError("AutonomousRuntime startup already in progress")
        if self._lifecycle_state == RuntimeLifecycleState.STOPPING:
            raise RuntimeError("AutonomousRuntime is stopping")
        
        self._lifecycle_state = RuntimeLifecycleState.STARTING
        self._started_components = []
        self._startup_exception = None
        
        try:
            # Phase 1: Recovery (synchronous, runs before async components)
            if auto_recover:
                if self.logger:
                    self.logger.get_logger(__name__).info("Running autonomous system recovery on startup")
                self.recovery_coordinator.recover()
            
            # Phase 2: Start executor (background thread)
            self.executor.start()
            self._started_components.append("executor")
            
            # Phase 3: Start message bus (async)
            await self.message_bus.start()
            self._started_components.append("message_bus")
            
            # Phase 4: Initialize skill catalog (discovers skills)
            if self.settings.skills.auto_discover:
                self.skill_catalog.initialize()
                self._started_components.append("skill_catalog")
            
            # Phase 5: Start Hermes runtime if enabled
            if self.hermes_backend:
                await self.hermes_backend.health_check()
                self._started_components.append("hermes_backend")
            
            self._lifecycle_state = RuntimeLifecycleState.STARTED
            
        except Exception as e:
            self._startup_exception = e
            self._lifecycle_state = RuntimeLifecycleState.FAILED
            # Rollback: stop components in reverse order
            await self._rollback_startup()
            raise
    
    async def _rollback_startup(self) -> None:
        """Rollback startup by stopping components in reverse order."""
        # Preserve the original exception
        original_exception = self._startup_exception
        
        # Stop in reverse order
        for component in reversed(self._started_components):
            try:
                if component == "hermes_backend" and self.hermes_backend:
                    # No explicit stop for hermes backend, just health check was called
                    pass
                elif component == "skill_catalog":
                    # No explicit stop for skill catalog
                    pass
                elif component == "message_bus":
                    await self.message_bus.stop()
                elif component == "executor":
                    self.executor.stop()
            except Exception as rollback_error:
                # Log rollback errors but don't mask original exception
                if self.logger:
                    self.logger.get_logger(__name__).error(
                        "Error during startup rollback for %s: %s",
                        component, rollback_error
                    )
        
        self._started_components = []
        # Re-raise the original exception
        if original_exception:
            raise original_exception
    
    async def stop(self) -> None:
        """
        Stop the autonomous runtime gracefully.
        
        Stops components in reverse dependency order:
        1. Hermes backend (if running)
        2. Message bus
        3. Executor
        
        Idempotent: safe to call multiple times, safe after failed startup.
        """
        if self._lifecycle_state in (RuntimeLifecycleState.STOPPED, RuntimeLifecycleState.CONSTRUCTED):
            return
        
        if self._lifecycle_state == RuntimeLifecycleState.STARTING:
            # Startup in progress - wait for it to complete or fail, then stop
            # For simplicity, we'll just rollback
            await self._rollback_startup()
            self._lifecycle_state = RuntimeLifecycleState.STOPPED
            return
        
        self._lifecycle_state = RuntimeLifecycleState.STOPPING
        
        # Stop in reverse order of startup
        # Note: We don't rely on _started_components for shutdown since
        # shutdown must work even after partial/failed startup
        
        # 1. Stop Hermes backend (no explicit stop, but we could add one)
        # Hermes backend doesn't have a stop method currently
        
        # 2. Stop message bus
        try:
            await self.message_bus.stop()
        except Exception as e:
            if self.logger:
                self.logger.get_logger(__name__).error("Error stopping message bus: %s", e)
        
        # 3. Stop executor (background thread)
        try:
            self.executor.stop()
        except Exception as e:
            if self.logger:
                self.logger.get_logger(__name__).error("Error stopping executor: %s", e)
        
        self._lifecycle_state = RuntimeLifecycleState.STOPPED
        self._started_components = []
    
    @property
    def is_started(self) -> bool:
        """Check if runtime is fully started."""
        return self._lifecycle_state == RuntimeLifecycleState.STARTED
    
    @property
    def is_stopped(self) -> bool:
        """Check if runtime is stopped."""
        return self._lifecycle_state in (RuntimeLifecycleState.STOPPED, RuntimeLifecycleState.CONSTRUCTED)
    
    @property
    def startup_exception(self) -> Optional[BaseException]:
        """Get the startup exception if startup failed."""
        return self._startup_exception


def build_autonomous_runtime(
    *,
    sync_pool: ConnectionPool,
    event_bus: EventBus,
    logger: Logger,
    service_container: ServiceContainer | None = None,
    auto_recover: bool = True,
    # Core services required for execution
    capability_resolver: CapabilityResolver,
    planner: Planner,
    capability_executor: CapabilityExecutor,
    tool_manager: ToolManager,
    provider_manager: ProviderManager,
    resource_manager: ResourceManager,
    policy_engine: PolicyEngine,
    permission_manager,          # type: PermissionManager (untyped in signature)
    workspace_permission_manager, # type: WorkspacePermissionManager (untyped in signature)
) -> AutonomousRuntime:
    """
    Build the complete autonomous runtime.
    
    Args:
        sync_pool: Synchronous PostgreSQL connection pool (from PoolManager.initialize_sync_pool())
        event_bus: Global event bus
        logger: Global logger
        service_container: Optional service container for registration
        auto_recover: Whether to run recovery on startup
        capability_resolver: Core capability resolver
        planner: Core planner
        capability_executor: Core capability executor
        tool_manager: Core tool manager
        provider_manager: Core provider manager
        resource_manager: Core resource manager
        policy_engine: Core policy engine
        permission_manager: Core permission manager
        workspace_permission_manager: Core workspace permission manager
        
    Returns:
        Fully constructed AutonomousRuntime
    """
    # Load configuration
    configuration = Configuration()
    configuration.load()
    autonomous_settings = load_autonomous_settings(configuration)
    
    # =========================================================================
    # REPOSITORIES
    # =========================================================================
    
    mission_repository = MissionRepository(sync_pool, logger)
    task_repository = AutonomousTaskRepository(sync_pool, logger)
    dependency_repository = TaskDependencyRepository(sync_pool, logger)
    agent_repository = AgentInstanceRepository(sync_pool, logger)
    worker_repository = WorkerRepository(sync_pool, logger)
    execution_repository = ExecutionRepository(sync_pool, logger)
    checkpoint_repository = CheckpointRepository(sync_pool, logger)
    world_state_repository = WorldStateRepository(sync_pool, logger)
    event_repository = AutonomousEventRepository(sync_pool, logger)
    message_repository = AgentMessageRepository(sync_pool, logger)
    
    # =========================================================================
    # MANAGERS
    # =========================================================================
    mission_manager = MissionManager(
        repository=mission_repository,
        event_bus=event_bus,
        logger=logger,
    )
    task_manager = AutonomousTaskManager(
        repository=task_repository,
        dependency_repository=dependency_repository,
        event_bus=event_bus,
        logger=logger,
    )
    worker_manager = WorkerManager(
        worker_repository=worker_repository,
        execution_repository=execution_repository,
        event_bus=event_bus,
        logger=logger,
    )
    checkpoint_manager = CheckpointManager(
        repository=checkpoint_repository,
        event_bus=event_bus,
        logger=logger,
    )
    recovery_coordinator = RecoveryCoordinator(
        mission_repository=mission_repository,
        task_repository=task_repository,
        dependency_repository=dependency_repository,
        agent_repository=agent_repository,
        worker_repository=worker_repository,
        execution_repository=execution_repository,
        checkpoint_manager=checkpoint_manager,
        event_bus=event_bus,
        logger=logger,
    )
    agent_supervisor = AgentSupervisor(
        repository=agent_repository,
        event_bus=event_bus,
        logger=logger,
    )
    world_state_manager = WorldStateManager(
        mission_repository=mission_repository,
        task_repository=task_repository,
        agent_repository=agent_repository,
        worker_repository=worker_repository,
        world_state_repository=world_state_repository,
        message_repository=message_repository,
        logger=logger,
    )
    
    # =========================================================================
    # AUTHORIZATION & BUDGET
    # =========================================================================
    authorization_boundary = create_autonomous_authorization_boundary(
        policy_engine=policy_engine,
        permission_manager=permission_manager,
        workspace_permission_manager=workspace_permission_manager,
        logger=logger,
    )
    budget_enforcer = BudgetEnforcer(
        resource_manager=resource_manager,
        logger=logger,
    )
    
    # =========================================================================
    # SKILL SYSTEM
    # =========================================================================
    security_scanner = SkillSecurityScanner(
        event_bus=event_bus,
        logger=logger,
        strict_mode=autonomous_settings.skills.strict_security_mode,
    )
    
    skill_registry = SkillRegistry(event_bus=event_bus, logger=logger)
    skill_registry.set_security_scanner(security_scanner)
    
    skill_catalog = SkillCatalog(
        registry=skill_registry,
        configuration=configuration,
        event_bus=event_bus,
        logger=logger,
    )
    
    skill_loader = SkillLoader(
        registry=skill_registry,
        security_scanner=security_scanner,
        policy_engine=policy_engine,
        permission_manager=permission_manager,
        workspace_permissions=workspace_permission_manager,
        event_bus=event_bus,
        logger=logger,
    )
    
    # =========================================================================
    # IMPLEMENTATION SYSTEM
    # =========================================================================
    implementation_registry = ImplementationRegistry(
        capability_registry=capability_resolver._capability_registry,
        tool_manager=tool_manager,
        skill_registry=skill_registry,
        event_bus=event_bus,
        logger=logger,
    )
    
    implementation_resolver = ImplementationResolver(
        capability_registry=capability_resolver._capability_registry,
        capability_resolver=capability_resolver,
        implementation_registry=implementation_registry,
        skill_registry=skill_registry,
        policy_engine=policy_engine,
        permission_manager=permission_manager,
        workspace_permissions=workspace_permission_manager,
        resource_manager=resource_manager,
        event_bus=event_bus,
        logger=logger,
    )
    
    # =========================================================================
    # RUNTIME REGISTRY (Availability Tracker)
    # =========================================================================
    runtime_registry = RuntimeRegistry(event_bus=event_bus, logger=logger)
    
    # =========================================================================
    # EXECUTION BACKENDS
    # =========================================================================
    # Native backend (always available)
    native_backend = NativeBackend(
        capability_executor=capability_executor,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
        capability_resolver=capability_resolver,
        planner=planner,
        logger=logger,
    )
    
    # Register native runtime
    native_config = RuntimeConfig(
        runtime_type=RuntimeType.NATIVE,
        runtime_id="native",
        name="PARIKA Native Runtime",
        config=MappingProxyType({}),
        resource_limits=MappingProxyType({"max_concurrent_agents": autonomous_settings.runtime.native_max_concurrent_agents}),
        enabled=autonomous_settings.runtime.native_enabled,
    )
    native_runtime_info = runtime_registry.register(
        runtime_type=RuntimeType.NATIVE,
        config=native_config,
        backend_instance=native_backend,
    )
    
    # Hermes backend (optional)
    hermes_backend = None
    if autonomous_settings.hermes.enabled and autonomous_settings.runtime.hermes_enabled:
        hermes_backend = HermesBackend(
            authorization_boundary=authorization_boundary,
            skill_loader=skill_loader,
            skill_registry=skill_registry,
            permission_manager=permission_manager,
            workspace_permissions=workspace_permission_manager,
            resource_manager=resource_manager,
            event_bus=event_bus,
            logger=logger,
            hermes_binary=autonomous_settings.hermes.binary_path,
            hermes_config_dir=autonomous_settings.hermes.config_dir,
        )
        
        hermes_config = RuntimeConfig(
            runtime_type=RuntimeType.HERMES,
            runtime_id="hermes",
            name="Hermes Runtime",
            config=MappingProxyType({
                "binary": autonomous_settings.hermes.binary_path,
                "config_dir": autonomous_settings.hermes.config_dir,
            }),
            resource_limits=MappingProxyType({"max_concurrent_agents": autonomous_settings.hermes.max_concurrent_agents}),
            enabled=autonomous_settings.runtime.hermes_enabled,
        )
        runtime_registry.register(
            runtime_type=RuntimeType.HERMES,
            config=hermes_config,
            backend_instance=hermes_backend,
        )
    
    # Remote backend (placeholder)
    remote_backend = RemoteBackend(logger=logger)
    remote_config = RuntimeConfig(
        runtime_type=RuntimeType.REMOTE,
        runtime_id="remote",
        name="Remote Runtime",
        enabled=False,  # Disabled by default
    )
    runtime_registry.register(
        runtime_type=RuntimeType.REMOTE,
        config=remote_config,
        backend_instance=remote_backend,
    )
    
    # =========================================================================
    # EXECUTION RESOLUTION AND DISPATCH
    # =========================================================================
    execution_strategy_resolver = ExecutionStrategyResolver(
        implementation_resolver=implementation_resolver,
        capability_registry=capability_resolver._capability_registry,
        runtime_registry=runtime_registry,
        authorization_boundary=authorization_boundary,
        budget_enforcer=budget_enforcer,
        event_bus=event_bus,
        logger=logger,
    )
    
    # Dispatcher with all backends
    backends: dict[str, ExecutionBackend] = {
        "native": native_backend,
        "hermes": hermes_backend if hermes_backend else None,
        "remote": remote_backend,
    }
    backends = {k: v for k, v in backends.items() if v is not None}
    
    dispatcher = ExecutionDispatcher(
        backends=backends,
        event_bus=event_bus,
        logger=logger,
    )
    
    # =========================================================================
    # AGENT COMMUNICATION
    # =========================================================================
    message_bus = MessageBus(
        repository=message_repository,
        agent_supervisor=agent_supervisor,
        event_bus=event_bus,
        logger=logger,
    )
    
    wait_manager = WaitManager(
        task_manager=task_manager,
        message_bus=message_bus,
        event_bus=event_bus,
        logger=logger,
    )
    
    # =========================================================================
    # MULTI-AGENT COORDINATION
    # =========================================================================
    mission_coordinator = MissionCoordinator(
        mission_manager=mission_manager,
        task_manager=task_manager,
        agent_supervisor=agent_supervisor,
        agent_orchestrator=None,  # Not needed for autonomous execution
        message_bus=message_bus,
        skill_loader=skill_loader,
        skill_catalog=skill_catalog,
        event_bus=event_bus,
        logger=logger,
    )
    
    agent_selector = AgentSelector(
        agent_registry=None,
        agent_resolver=None,
        agent_orchestrator=None,
        capability_registry=capability_resolver._capability_registry,
        capability_resolver=capability_resolver,
        implementation_registry=implementation_registry,
        implementation_resolver=implementation_resolver,
        skill_registry=skill_registry,
        skill_catalog=skill_catalog,
        event_bus=event_bus,
        logger=logger,
    )
    
    wait_manager_instance = wait_manager
    
    # =========================================================================
    # EXECUTOR
    # =========================================================================
    executor = AutonomousExecutor(
        task_repository=task_repository,
        task_manager=task_manager,
        worker_manager=worker_manager,
        checkpoint_manager=checkpoint_manager,
        capability_resolver=capability_resolver,
        planner=planner,
        capability_executor=capability_executor,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
        resource_manager=resource_manager,
        policy_engine=policy_engine,
        mission_manager=mission_manager,
        authorization_boundary=authorization_boundary,
        budget_enforcer=budget_enforcer,
        agent_supervisor=agent_supervisor,
        event_bus=event_bus,
        logger=logger,
        # New architecture components
        execution_strategy_resolver=execution_strategy_resolver,
        dispatcher=dispatcher,
        runtime_registry=runtime_registry,
        mission_coordinator=mission_coordinator,
    )
    
    # =========================================================================
    # SERVICE CONTAINER REGISTRATION
    # =========================================================================
    if service_container:
        _register_services(service_container, locals())
    
    # =========================================================================
    # AUTONOMOUS RUNTIME ASSEMBLY
    # =========================================================================
    runtime = AutonomousRuntime(
        settings=autonomous_settings,
        configuration=configuration,
        sync_pool=sync_pool,
        event_bus=event_bus,
        logger=logger,
        service_container=service_container,
        
        # Core services
        capability_resolver=capability_resolver,
        planner=planner,
        capability_executor=capability_executor,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
        resource_manager=resource_manager,
        policy_engine=policy_engine,
        permission_manager=permission_manager,
        workspace_permission_manager=workspace_permission_manager,
        
        # Repositories
        mission_repository=mission_repository,
        task_repository=task_repository,
        dependency_repository=dependency_repository,
        agent_repository=agent_repository,
        worker_repository=worker_repository,
        execution_repository=execution_repository,
        checkpoint_repository=checkpoint_repository,
        world_state_repository=world_state_repository,
        event_repository=event_repository,
        message_repository=message_repository,
        
        # Managers
        mission_manager=mission_manager,
        task_manager=task_manager,
        worker_manager=worker_manager,
        checkpoint_manager=checkpoint_manager,
        recovery_coordinator=recovery_coordinator,
        agent_supervisor=agent_supervisor,
        world_state_manager=world_state_manager,
        
        # Authorization & Budget
        authorization_boundary=authorization_boundary,
        budget_enforcer=budget_enforcer,
        
        # Skill system
        skill_registry=skill_registry,
        skill_catalog=skill_catalog,
        skill_loader=skill_loader,
        security_scanner=security_scanner,
        
        # Implementation system
        implementation_registry=implementation_registry,
        implementation_resolver=implementation_resolver,
        
        # Runtime registry
        runtime_registry=runtime_registry,
        
        # Execution backends
        native_backend=native_backend,
        hermes_backend=hermes_backend,
        remote_backend=remote_backend,
        
        # Execution resolution and dispatch
        execution_strategy_resolver=execution_strategy_resolver,
        dispatcher=dispatcher,
        
        # Agent communication
        message_bus=message_bus,
        wait_manager=wait_manager,
        
        # Multi-agent
        mission_coordinator=mission_coordinator,
        agent_selector=agent_selector,
        
        # Autonomous waiting
        wait_manager_instance=wait_manager_instance,
        
        # Core executor
        executor=executor,
    )
    
    # =========================================================================
    # POST-CONSTRUCTION FIXUPS
    # =========================================================================
    # The native backend needs a reference to the executor for actual execution
    # This is handled by the dispatcher using the native_backend directly
    
    return runtime


def _register_services(service_container: ServiceContainer, components: dict) -> None:
    """Register all autonomous services in the service container."""
    # Register core autonomous services
    service_map = {
        "autonomous.mission_manager": components["mission_manager"],
        "autonomous.task_manager": components["task_manager"],
        "autonomous.worker_manager": components["worker_manager"],
        "autonomous.checkpoint_manager": components["checkpoint_manager"],
        "autonomous.recovery_coordinator": components["recovery_coordinator"],
        "autonomous.agent_supervisor": components["agent_supervisor"],
        "autonomous.world_state_manager": components["world_state_manager"],
        "autonomous.authorization_boundary": components["authorization_boundary"],
        "autonomous.budget_enforcer": components["budget_enforcer"],
        "autonomous.skill_registry": components["skill_registry"],
        "autonomous.skill_catalog": components["skill_catalog"],
        "autonomous.skill_loader": components["skill_loader"],
        "autonomous.security_scanner": components["security_scanner"],
        "autonomous.implementation_registry": components["implementation_registry"],
        "autonomous.implementation_resolver": components["implementation_resolver"],
        "autonomous.runtime_registry": components["runtime_registry"],
        "autonomous.native_backend": components["native_backend"],
        "autonomous.hermes_backend": components["hermes_backend"],
        "autonomous.remote_backend": components["remote_backend"],
        "autonomous.execution_strategy_resolver": components["execution_strategy_resolver"],
        "autonomous.dispatcher": components["dispatcher"],
        "autonomous.message_bus": components["message_bus"],
        "autonomous.wait_manager": components["wait_manager_instance"],
        "autonomous.mission_coordinator": components["mission_coordinator"],
        "autonomous.agent_selector": components["agent_selector"],
        "autonomous.executor": components["executor"],
    }
    
    for key, service in service_map.items():
        if service is not None:
            service_container.register(key, service)