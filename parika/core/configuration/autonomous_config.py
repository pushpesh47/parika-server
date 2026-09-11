"""
PARIKA Autonomous Runtime Configuration

Configuration settings for skills, runtimes, Hermes, and multi-agent features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from parika.core.configuration.configuration import Configuration


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillSettings:
    """Skill system configuration."""
    enabled: bool = True
    local_skills_dir: str = "skills"
    user_skills_dir: str = "user_skills"
    community_skills_dir: str = "community_skills"
    auto_discover: bool = True
    security_scanner_enabled: bool = True
    strict_security_mode: bool = False
    default_trust_state: str = "discovered"
    max_skills_per_source: int = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class HermesSettings:
    """Hermes runtime integration configuration."""
    enabled: bool = True
    binary_path: str = "hermes"
    config_dir: str | None = None  # Defaults to ~/.hermes
    skills_dir: str | None = None  # Defaults to ~/.hermes/skills
    max_concurrent_agents: int = 5
    process_timeout_seconds: int = 300
    heartbeat_interval_seconds: int = 10
    session_timeout_seconds: int = 120
    auto_import_skills: bool = True
    skill_sync_interval_seconds: int = 3600
    resource_limits: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeSettings:
    """Runtime configuration."""
    native_enabled: bool = True
    native_max_concurrent_agents: int = 10
    hermes_enabled: bool = True
    hermes_max_concurrent_agents: int = 5
    remote_enabled: bool = False
    default_runtime: str = "native"
    runtime_selection_policy: str = "auto"  # "auto", "native", "hermes", "remote"


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentCommunicationSettings:
    """Agent-to-agent communication configuration."""
    enabled: bool = True
    message_ttl_seconds: int = 3600
    max_retries: int = 3
    delivery_interval_seconds: int = 5
    cleanup_expired_interval_seconds: int = 3600


@dataclass(frozen=True, slots=True, kw_only=True)
class MultiAgentSettings:
    """Multi-agent coordination configuration."""
    enabled: bool = True
    max_agents_per_mission: int = 20
    default_agent_profile: str = "agent.general"
    concurrent_execution: bool = True
    isolation_mode: str = "process"  # "none", "process", "container"


@dataclass(frozen=True, slots=True, kw_only=True)
class AutonomousWaitingSettings:
    """Event-driven autonomous waiting configuration."""
    enabled: bool = True
    max_wait_conditions_per_task: int = 10
    default_timeout_seconds: int = 300
    cleanup_interval_seconds: int = 60
    dependency_check_interval_seconds: int = 10


@dataclass(frozen=True, slots=True, kw_only=True)
class AutonomousSettings:
    """Complete autonomous runtime configuration."""
    skills: SkillSettings = field(default_factory=SkillSettings)
    hermes: HermesSettings = field(default_factory=HermesSettings)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    agent_communication: AgentCommunicationSettings = field(default_factory=AgentCommunicationSettings)
    multi_agent: MultiAgentSettings = field(default_factory=MultiAgentSettings)
    autonomous_waiting: AutonomousWaitingSettings = field(default_factory=AutonomousWaitingSettings)


def load_autonomous_settings(configuration: Configuration) -> AutonomousSettings:
    """
    Load autonomous runtime settings from configuration.
    """
    # Skills
    skills = SkillSettings(
        enabled=bool(configuration.get("skills.enabled", True)),
        local_skills_dir=str(configuration.get("skills.local_skills_dir", "skills")),
        user_skills_dir=str(configuration.get("skills.user_skills_dir", "user_skills")),
        community_skills_dir=str(configuration.get("skills.community_skills_dir", "community_skills")),
        auto_discover=bool(configuration.get("skills.auto_discover", True)),
        security_scanner_enabled=bool(configuration.get("skills.security_scanner_enabled", True)),
        strict_security_mode=bool(configuration.get("skills.strict_security_mode", False)),
        default_trust_state=str(configuration.get("skills.default_trust_state", "discovered")),
        max_skills_per_source=int(configuration.get("skills.max_skills_per_source", 1000)),
    )

    # Hermes
    hermes = HermesSettings(
        enabled=bool(configuration.get("hermes.enabled", True)),
        binary_path=str(configuration.get("hermes.binary_path", "hermes")),
        config_dir=configuration.get("hermes.config_dir"),
        skills_dir=configuration.get("hermes.skills_dir"),
        max_concurrent_agents=int(configuration.get("hermes.max_concurrent_agents", 5)),
        process_timeout_seconds=int(configuration.get("hermes.process_timeout_seconds", 300)),
        heartbeat_interval_seconds=int(configuration.get("hermes.heartbeat_interval_seconds", 10)),
        session_timeout_seconds=int(configuration.get("hermes.session_timeout_seconds", 120)),
        auto_import_skills=bool(configuration.get("hermes.auto_import_skills", True)),
        skill_sync_interval_seconds=int(configuration.get("hermes.skill_sync_interval_seconds", 3600)),
        resource_limits=dict(configuration.get("hermes.resource_limits", {})),
    )

    # Runtime
    runtime = RuntimeSettings(
        native_enabled=bool(configuration.get("runtime.native_enabled", True)),
        native_max_concurrent_agents=int(configuration.get("runtime.native_max_concurrent_agents", 10)),
        hermes_enabled=bool(configuration.get("runtime.hermes_enabled", True)),
        hermes_max_concurrent_agents=int(configuration.get("runtime.hermes_max_concurrent_agents", 5)),
        remote_enabled=bool(configuration.get("runtime.remote_enabled", False)),
        default_runtime=str(configuration.get("runtime.default_runtime", "native")),
        runtime_selection_policy=str(configuration.get("runtime.runtime_selection_policy", "auto")),
    )

    # Agent Communication
    agent_communication = AgentCommunicationSettings(
        enabled=bool(configuration.get("agent_communication.enabled", True)),
        message_ttl_seconds=int(configuration.get("agent_communication.message_ttl_seconds", 3600)),
        max_retries=int(configuration.get("agent_communication.max_retries", 3)),
        delivery_interval_seconds=int(configuration.get("agent_communication.delivery_interval_seconds", 5)),
        cleanup_expired_interval_seconds=int(configuration.get("agent_communication.cleanup_expired_interval_seconds", 3600)),
    )

    # Multi-Agent
    multi_agent = MultiAgentSettings(
        enabled=bool(configuration.get("multi_agent.enabled", True)),
        max_agents_per_mission=int(configuration.get("multi_agent.max_agents_per_mission", 20)),
        default_agent_profile=str(configuration.get("multi_agent.default_agent_profile", "agent.general")),
        concurrent_execution=bool(configuration.get("multi_agent.concurrent_execution", True)),
        isolation_mode=str(configuration.get("multi_agent.isolation_mode", "process")),
    )

    # Autonomous Waiting
    autonomous_waiting = AutonomousWaitingSettings(
        enabled=bool(configuration.get("autonomous_waiting.enabled", True)),
        max_wait_conditions_per_task=int(configuration.get("autonomous_waiting.max_wait_conditions_per_task", 10)),
        default_timeout_seconds=int(configuration.get("autonomous_waiting.default_timeout_seconds", 300)),
        cleanup_interval_seconds=int(configuration.get("autonomous_waiting.cleanup_interval_seconds", 60)),
        dependency_check_interval_seconds=int(configuration.get("autonomous_waiting.dependency_check_interval_seconds", 10)),
    )

    return AutonomousSettings(
        skills=skills,
        hermes=hermes,
        runtime=runtime,
        agent_communication=agent_communication,
        multi_agent=multi_agent,
        autonomous_waiting=autonomous_waiting,
    )