"""
PARIKA Autonomous Execution - Autonomous Runtime

Main entry point for autonomous execution subsystem.
Integrates with PARIKA Core via ServiceContainer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.contracts import MissionStatus, AutonomousTaskStatus
from parika.core.autonomous.mission_manager import MissionManager
from parika.core.autonomous.task_manager import AutonomousTaskManager
from parika.core.autonomous.worker_manager import WorkerManager
from parika.core.autonomous.checkpoint_manager import CheckpointManager
from parika.core.autonomous.recovery_coordinator import RecoveryCoordinator
from parika.core.autonomous.agent_supervisor import AgentSupervisor
from parika.core.autonomous.world_state_manager import WorldStateManager
from parika.core.autonomous.executor import AutonomousExecutor, ExecutorConfig
from parika.core.autonomous.authorization import AutonomousAuthorizationBoundary, create_autonomous_authorization_boundary
from parika.core.autonomous.budget import BudgetEnforcer
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
)
from parika.core.database.pool import PoolManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.service_container.service_container import ServiceContainer
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.planner import Planner
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.policy_engine.policy_engine import PolicyEngine

# Phase 2 imports
from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.skill_system.skill_catalog import SkillCatalog
from parika.core.skill_system.skill_loader import SkillLoader
from parika.core.skill_system.skill_security import SkillSecurityScanner
from parika.core.implementation_registry.implementation_registry import ImplementationRegistry
from parika.core.implementation_registry.implementation_resolver import ImplementationResolver
from parika.core.agent_runtime.runtime_registry import RuntimeRegistry
from parika.core.agent_runtime.contracts import RuntimeConfig, RuntimeType
from parika.core.agent_runtime.native_runtime import NativeRuntimeAdapter
from parika.core.agent_runtime.hermes_runtime import HermesRuntimeAdapter
from parika.core.agent_communication.message_bus import MessageBus
from parika.core.agent_communication.message_repository import AgentMessageRepository
from parika.core.multi_agent.mission_coordinator import MissionCoordinator
from parika.core.multi_agent.agent_selector import AgentSelector
from parika.core.configuration.phase2_config import Phase2Settings, load_phase2_settings
from parika.core.configuration.configuration import Configuration

# Phase 2 - wait manager (lazy import to avoid circular dependency)
try:
    from parika.core.autonomous_waiting.wait_manager import WaitManager
except ImportError:
    WaitManager = None


@dataclass(slots=True, kw_only=True)
class AutonomousRuntime:
    """
    Autonomous execution runtime.
    
    Coordinates all autonomous execution components and provides
    a unified interface for creating and managing autonomous work.
    """
    
    mission_manager: MissionManager
    task_manager: AutonomousTaskManager
    worker_manager: WorkerManager
    checkpoint_manager: CheckpointManager
    recovery_coordinator: RecoveryCoordinator
    agent_supervisor: AgentSupervisor
    world_state_manager: WorldStateManager
    executor: "AutonomousExecutor"
    
    # Phase 2 services
    skill_registry: SkillRegistry
    skill_catalog: SkillCatalog
    skill_loader: SkillLoader
    security_scanner: SkillSecurityScanner
    implementation_registry: ImplementationRegistry
    implementation_resolver: ImplementationResolver
    runtime_registry: RuntimeRegistry
    message_bus: MessageBus
    wait_manager: WaitManager
    mission_coordinator: MissionCoordinator
    agent_selector: AgentSelector
    
    # Repositories (for advanced use cases)
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


def build_autonomous_runtime(
    *,
    pool_manager: PoolManager,
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
    permission_manager,
    workspace_permission_manager,
) -> AutonomousRuntime:
    """
    Build the autonomous execution runtime.
    
    Args:
        pool_manager: PostgreSQL connection pool manager
        event_bus: PARIKA EventBus for event publishing
        logger: PARIKA Logger
        service_container: Optional ServiceContainer to register components
        auto_recover: Whether to automatically run recovery on startup
        capability_resolver: CapabilityResolver from Core
        planner: Planner from Core
        capability_executor: CapabilityExecutor from Core
        tool_manager: ToolManager from Core
        provider_manager: ProviderManager from Core
        resource_manager: ResourceManager from Core
        policy_engine: PolicyEngine from Core
        permission_manager: PermissionManager from Core
        workspace_permission_manager: WorkspacePermissionManager from Core
        
    Returns:
        Configured AutonomousRuntime instance
    """
    autonomous_logger = logger.get_logger("parika.autonomous")
    
    # Load Phase 2 configuration
    configuration = Configuration()
    configuration.load()
    phase2_settings = load_phase2_settings(configuration)
    
    # Create repositories
    mission_repository = MissionRepository(pool_manager, logger)
    task_repository = AutonomousTaskRepository(pool_manager, logger)
    dependency_repository = TaskDependencyRepository(pool_manager, logger)
    agent_repository = AgentInstanceRepository(pool_manager, logger)
    worker_repository = WorkerRepository(pool_manager, logger)
    execution_repository = ExecutionRepository(pool_manager, logger)
    checkpoint_repository = CheckpointRepository(pool_manager, logger)
    world_state_repository = WorldStateRepository(pool_manager, logger)
    event_repository = AutonomousEventRepository(pool_manager, logger)
    message_repository = AgentMessageRepository(pool_manager, logger)
    
    # Create managers
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
    
    # Authorization & Budget
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
    
    # Phase 2: Skill System
    security_scanner = SkillSecurityScanner(
        event_bus=event_bus,
        logger=logger,
        strict_mode=phase2_settings.skills.strict_security_mode,
    )
    
    skill_registry = SkillRegistry(
        event_bus=event_bus,
        logger=logger,
    )
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
    
    # Phase 2: Implementation Registry
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
    
    # Phase 2: Runtime Registry
    runtime_registry = RuntimeRegistry(
        event_bus=event_bus,
        logger=logger,
    )
    
    # Register Native Runtime
    native_config = RuntimeConfig(
        runtime_type=RuntimeType.NATIVE,
        runtime_id="native",
        name="PARIKA Native Runtime",
        config=MappingProxyType({}),
        resource_limits=MappingProxyType({"max_concurrent_agents": phase2_settings.runtime.native_max_concurrent_agents}),
        enabled=phase2_settings.runtime.native_enabled,
    )
    
    native_runtime = NativeRuntimeAdapter(
        config=native_config,
        executor=None,  # Will be set after executor creation
        agent_supervisor=agent_supervisor,
        capability_executor=capability_executor,
        tool_manager=tool_manager,
        agent_orchestrator=None,  # Will be set after orchestrator is available
        task_manager=task_manager,
        event_bus=event_bus,
        logger=logger,
    )
    runtime_registry.register(native_runtime, native_config)
    
    # Register Hermes Runtime if enabled
    if phase2_settings.hermes.enabled and phase2_settings.runtime.hermes_enabled:
        hermes_config = RuntimeConfig(
            runtime_type=RuntimeType.HERMES,
            runtime_id="hermes",
            name="Hermes Runtime",
            config=MappingProxyType({}),
            resource_limits=MappingProxyType({"max_concurrent_agents": phase2_settings.hermes.max_concurrent_agents}),
            enabled=True,
        )
        
        hermes_runtime = HermesRuntimeAdapter(
            config=hermes_config,
            agent_supervisor=agent_supervisor,
            authorization_boundary=None,  # Will be set after boundary creation
            checkpoint_manager=checkpoint_manager,
            skill_loader=skill_loader,
            skill_registry=skill_registry,
            permission_manager=permission_manager,
            workspace_permissions=workspace_permission_manager,
            resource_manager=resource_manager,
            event_bus=event_bus,
            logger=logger,
            hermes_binary=phase2_settings.hermes.binary_path,
            hermes_config_dir=phase2_settings.hermes.config_dir,
        )
        runtime_registry.register(hermes_runtime, hermes_config)
    
    # Phase 2: Agent Communication
    message_bus = MessageBus(
        repository=message_repository,
        agent_supervisor=agent_supervisor,
        event_bus=event_bus,
        logger=logger,
    )
    
    # Phase 2: Wait Manager
    wait_manager = WaitManager(
        task_manager=task_manager,
        message_bus=message_bus,
        event_bus=event_bus,
        logger=logger,
    )
    
    # Phase 2: Multi-Agent Coordination
    mission_coordinator = MissionCoordinator(
        mission_manager=mission_manager,
        task_manager=task_manager,
        agent_supervisor=agent_supervisor,
        agent_orchestrator=None,  # Will be set later if available
        message_bus=message_bus,
        skill_loader=skill_loader,
        skill_catalog=skill_catalog,
        event_bus=event_bus,
        logger=logger,
    )
    
    agent_selector = AgentSelector(
        agent_registry=None,  # Will be set later if available
        agent_resolver=None,
        agent_orchestrator=None,
        capability_registry=capability_resolver._capability_registry,
        capability_resolver=capability_resolver,
        implementation_registry=implementation_registry,
        implementation_resolver=implementation_resolver,
        skill_registry=skill_registry,
        skill_catalog=skill_catalog,
        runtime_registry=runtime_registry,
        event_bus=event_bus,
        logger=logger,
    )
    
    # Executor
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
        authorization_boundary=authorization_boundary,
        budget_enforcer=budget_enforcer,
        agent_supervisor=agent_supervisor,
        event_bus=event_bus,
        logger=logger,
        # Phase 2 services
        skill_loader=skill_loader,
        skill_catalog=skill_catalog,
        implementation_resolver=implementation_resolver,
        runtime_registry=runtime_registry,
        mission_coordinator=mission_coordinator,
        wait_manager=wait_manager,
        message_bus=message_bus,
    )
    
    # Update NativeRuntimeAdapter with executor reference
    native_runtime._executor = executor
    
    # Update Hermes Runtime with authorization boundary
    if phase2_settings.hermes.enabled and phase2_settings.runtime.hermes_enabled:
        hermes_runtime._authorization_boundary = authorization_boundary
    
    # Update WorldStateManager with Phase 2 services
    world_state_manager._skill_registry = skill_registry
    world_state_manager._runtime_registry = runtime_registry
    world_state_manager._wait_manager = wait_manager
    
    runtime = AutonomousRuntime(
        mission_manager=mission_manager,
        task_manager=task_manager,
        worker_manager=worker_manager,
        checkpoint_manager=checkpoint_manager,
        recovery_coordinator=recovery_coordinator,
        agent_supervisor=agent_supervisor,
        world_state_manager=world_state_manager,
        executor=executor,
        skill_registry=skill_registry,
        skill_catalog=skill_catalog,
        skill_loader=skill_loader,
        security_scanner=security_scanner,
        implementation_registry=implementation_registry,
        implementation_resolver=implementation_resolver,
        runtime_registry=runtime_registry,
        message_bus=message_bus,
        wait_manager=wait_manager,
        mission_coordinator=mission_coordinator,
        agent_selector=agent_selector,
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
    )
    
    # Register with service container if provided
    if service_container is not None:
        service_container.register(AutonomousRuntime, runtime)
        service_container.register(MissionManager, mission_manager)
        service_container.register(AutonomousTaskManager, task_manager)
        service_container.register(WorkerManager, worker_manager)
        service_container.register(CheckpointManager, checkpoint_manager)
        service_container.register(RecoveryCoordinator, recovery_coordinator)
        service_container.register(AgentSupervisor, agent_supervisor)
        service_container.register(WorldStateManager, world_state_manager)
        service_container.register(AutonomousExecutor, executor)
        service_container.register(AutonomousAuthorizationBoundary, authorization_boundary)
        service_container.register(BudgetEnforcer, budget_enforcer)
        # Phase 2 services
        service_container.register(SkillRegistry, skill_registry)
        service_container.register(SkillCatalog, skill_catalog)
        service_container.register(SkillLoader, skill_loader)
        service_container.register(SkillSecurityScanner, security_scanner)
        service_container.register(ImplementationRegistry, implementation_registry)
        service_container.register(ImplementationResolver, implementation_resolver)
        service_container.register(RuntimeRegistry, runtime_registry)
        service_container.register(MessageBus, message_bus)
        service_container.register(WaitManager, wait_manager)
        service_container.register(MissionCoordinator, mission_coordinator)
        service_container.register(AgentSelector, agent_selector)
    
    # Run recovery if enabled
    if auto_recover:
        autonomous_logger.info("Running autonomous system recovery on startup")
        recovery_result = recovery_coordinator.recover()
        autonomous_logger.info("Recovery completed: %s", recovery_result)
    
    # Start executor after recovery
    executor.start()
    autonomous_logger.info("AutonomousExecutor started")
    
    # Start message bus
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(message_bus.start())
    except RuntimeError:
        # No event loop running yet
        pass
    
    # Initialize skill catalog (discover skills)
    if phase2_settings.skills.auto_discover:
        skill_catalog.initialize()
    
    # Start Hermes runtime if enabled
    if phase2_settings.hermes.enabled and phase2_settings.runtime.hermes_enabled:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(hermes_runtime.start())
        except RuntimeError:
            pass
    
    return runtime