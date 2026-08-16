"""
PARIKA API - Status Handler

Mirrors the existing `/status` slash command
(`parika/interfaces/commands/builtin.py:_handle_status`), reading the
same read-only Core managers, returning a plain, JSON-serializable
value rather than pre-formatted text.

The runtime/system telemetry groups (`system`, `cpu`, `memory`,
`gpu`, `temperature`, `storage`, `network`) are sourced exclusively
from `ResourceManager.get_resource_snapshot()` - one on-demand read
per request, exactly like every other existing caller of
`ResourceManager` (see docs/architecture/Core_Component_Responsibilities.md
section 8). No new caching, polling, or event publication is
introduced here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from parika.core.resource_manager.models import ResourceSnapshot
from parika.interfaces.runtime import ParikaRuntime

from ..requests import StatusRequest

_DEFAULT_APPLICATION_VERSION = "0.2.25-alpha"


def handle_status(runtime: ParikaRuntime, request: StatusRequest | None) -> dict[str, Any]:
    """
    Assemble the aggregate runtime status snapshot.

    Orchestrates already-existing, independent read-only Core calls
    (`StateManager`, `HealthManager`, `ModuleManager`,
    `ProviderManager`, `ResourceManager`, `MemoryManager`,
    `KnowledgeManager`) into one response -- composition of existing
    introspection, never a new decision.
    """

    uptime_seconds = (datetime.now(UTC) - runtime.started_at).total_seconds()

    providers = []
    available_providers = 0
    total_models = 0

    for provider in runtime.provider_manager.get_all():
        health = provider.health
        available = None if health is None else health.available

        if available:
            available_providers += 1

        total_models += len(provider.models)

        providers.append(
            {
                "id": provider.id,
                "enabled": provider.enabled,
                "available": available,
                "model_count": len(provider.models),
            }
        )

    snapshot = runtime.resource_manager.get_resource_snapshot()
    memory_stats = runtime.memory_manager.stats()
    app_version = runtime.configuration.get(
        "application.version", _DEFAULT_APPLICATION_VERSION
    )
    expose_hostname = bool(runtime.configuration.get("api.expose_hostname", False))

    return {
        "uptime_seconds": uptime_seconds,
        "lifecycle_state": runtime.state_manager.get_lifecycle_state().value,
        "execution_state": runtime.state_manager.get_execution_state().value,
        "interaction_state": runtime.state_manager.get_interaction_state().value,
        "overall_health": runtime.health_manager.overall_status().value,
        "active_modules": len(runtime.module_manager.get_active()),
        "total_modules": len(runtime.module_manager.get_all()),
        "registered_capabilities": len(runtime.capability_registry.get_all()),
        "registered_tools": runtime.tool_manager.count(),
        "registered_providers": runtime.provider_manager.count(),
        "providers": providers,
        **_build_telemetry(snapshot, expose_hostname=expose_hostname),
        "parika": {
            "version": app_version,
            "available_providers": available_providers,
            "total_models": total_models,
            "memory_count": memory_stats.total,
            "memory_storage_bytes": memory_stats.storage_size_bytes,
            "knowledge_engines": runtime.knowledge_manager.count_engines(),
            "knowledge_sources": runtime.knowledge_manager.count_sources(),
        },
        "timestamp": snapshot.timestamp,
    }


def _build_telemetry(
    snapshot: ResourceSnapshot, *, expose_hostname: bool
) -> dict[str, Any]:
    """
    Translate a `ResourceSnapshot` into the `system`/`cpu`/`memory`/
    `gpu`/`temperature`/`storage`/`network` API telemetry groups.

    `expose_hostname` gates the only host-identifying field
    (`system.hostname`/`network.hostname`): unlike the `/status` CLI
    command (already running on the user's own machine), this REST
    response may be reachable from other devices, so the hostname is
    redacted to `None` unless an operator explicitly opts in via
    `api.expose_hostname` (see `config/defaults.toml`).
    """

    return {
        "system": {
            "platform": snapshot.system.platform,
            "operating_system": snapshot.system.operating_system,
            "kernel_release": snapshot.system.kernel_release,
            "architecture": snapshot.system.architecture,
            "hostname": snapshot.system.hostname if expose_hostname else None,
            "boot_time": snapshot.system.boot_time,
            "uptime_seconds": snapshot.system.uptime_seconds,
            "uptime_human": snapshot.system.uptime_human,
        },
        "cpu": {
            "usage_percent": snapshot.cpu.usage_percent,
            "logical_core_count": snapshot.cpu.logical_core_count,
            "physical_core_count": snapshot.cpu.physical_core_count,
            "load_average_1m": snapshot.cpu.load_average_1m,
            "load_average_5m": snapshot.cpu.load_average_5m,
            "load_average_15m": snapshot.cpu.load_average_15m,
            "current_frequency_mhz": snapshot.cpu.current_frequency_mhz,
        },
        "memory": {
            "total_bytes": snapshot.memory.total_bytes,
            "available_bytes": snapshot.memory.available_bytes,
            "used_bytes": snapshot.memory.used_bytes,
            "usage_percent": snapshot.memory.usage_percent,
            "free_bytes": snapshot.memory.free_bytes,
            "swap_total_bytes": snapshot.memory.swap_total_bytes,
            "swap_used_bytes": snapshot.memory.swap_used_bytes,
            "swap_free_bytes": snapshot.memory.swap_free_bytes,
            "swap_usage_percent": snapshot.memory.swap_usage_percent,
        },
        "gpu": {
            "detected": snapshot.gpu.detected,
            "available": snapshot.gpu.status.value == "available",
            "devices": [
                {
                    "index": device.index,
                    "name": device.name,
                    "vendor": device.vendor,
                    "utilization_percent": device.utilization_percent,
                    "memory_total_bytes": device.memory_total_bytes,
                    "memory_used_bytes": device.memory_used_bytes,
                    "memory_free_bytes": device.memory_free_bytes,
                    "memory_usage_percent": device.memory_usage_percent,
                    "temperature_celsius": device.temperature_celsius,
                    "power_usage_watts": device.power_usage_watts,
                    "power_limit_watts": device.power_limit_watts,
                }
                for device in snapshot.gpu.devices
            ],
        },
        "temperature": {
            "available": bool(snapshot.temperature.sensors),
            "sensors": [
                {
                    "label": sensor.label,
                    "current_celsius": sensor.current_celsius,
                    "high_celsius": sensor.high_celsius,
                    "critical_celsius": sensor.critical_celsius,
                }
                for sensor in snapshot.temperature.sensors
            ],
        },
        "storage": {
            "path": str(snapshot.disk.path),
            "total_bytes": snapshot.disk.total_bytes,
            "used_bytes": snapshot.disk.used_bytes,
            "free_bytes": snapshot.disk.free_bytes,
            "usage_percent": snapshot.disk.usage_percent,
        },
        "network": {
            "available": snapshot.network.status.value == "available",
            "hostname": snapshot.network.hostname if expose_hostname else None,
            "interface_count": snapshot.network.interface_count,
            "active_interface_count": snapshot.network.active_interface_count,
            "bytes_sent": snapshot.network.bytes_sent,
            "bytes_received": snapshot.network.bytes_received,
            "interfaces": [
                {
                    "name": interface.name,
                    "is_up": interface.is_up,
                    "bytes_sent": interface.bytes_sent,
                    "bytes_received": interface.bytes_received,
                }
                for interface in snapshot.network.interfaces
            ],
        },
    }
