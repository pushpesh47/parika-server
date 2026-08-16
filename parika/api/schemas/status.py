"""
PARIKA API - Status Schemas

Mirrors the existing `/status` slash command's fields (see
`parika/interfaces/commands/builtin.py:_handle_status`), exposed as a
typed, versioned response instead of pre-formatted text.

`StatusResponse` additionally exposes a unified runtime/system
telemetry snapshot (`system`, `cpu`, `memory`, `gpu`, `temperature`,
`storage`, `network`) sourced exclusively from `ResourceManager` -
see `parika/core/resource_manager/` - and a `parika` block for
PARIKA-runtime counts/statistics that are not already flat fields on
this response (version, provider availability, long-term memory and
knowledge statistics). Every nested field that cannot be determined on
the current host/build is `null`, never a fabricated zero, per
docs/architecture/Core_Component_Responsibilities.md section 8.
"""

from __future__ import annotations

from datetime import datetime

from .common import ApiModel


class StatusProviderSummary(ApiModel):
    """
    Lightweight per-provider summary embedded in `StatusResponse`.

    Deliberately named distinctly from `schemas.providers
    .ProviderSummary` (the fuller listing returned by `/api/v1/providers`,
    including `name`, `state`, and `models`) even though both mirror
    the same underlying `ProviderManager` data, to avoid two
    differently-shaped classes sharing one name across the schema
    package.
    """

    id: str
    enabled: bool
    available: bool | None = None
    model_count: int


class StatusSystemInfo(ApiModel):
    """
    Host operating system, architecture, and uptime information.

    `hostname` is `null` unless the operator has explicitly opted in
    via `api.expose_hostname` (default `false` - see
    `config/defaults.toml`), since this REST response, unlike the
    `/status` CLI command, may be reachable from other devices.
    """

    platform: str
    operating_system: str
    kernel_release: str | None = None
    architecture: str
    hostname: str | None = None
    boot_time: datetime | None = None
    uptime_seconds: float | None = None
    uptime_human: str | None = None


class StatusCPUInfo(ApiModel):
    """Host CPU utilization and identity information."""

    usage_percent: float
    logical_core_count: int
    physical_core_count: int | None = None
    load_average_1m: float | None = None
    load_average_5m: float | None = None
    load_average_15m: float | None = None
    current_frequency_mhz: float | None = None


class StatusMemoryInfo(ApiModel):
    """Host memory (RAM) utilization, in raw bytes and percentages."""

    total_bytes: int
    available_bytes: int
    used_bytes: int
    usage_percent: float
    free_bytes: int | None = None
    swap_total_bytes: int | None = None
    swap_used_bytes: int | None = None
    swap_free_bytes: int | None = None
    swap_usage_percent: float | None = None


class StatusGPUDeviceInfo(ApiModel):
    """Telemetry for a single detected GPU device."""

    index: int
    name: str | None = None
    vendor: str | None = None
    utilization_percent: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    memory_free_bytes: int | None = None
    memory_usage_percent: float | None = None
    temperature_celsius: float | None = None
    power_usage_watts: float | None = None
    power_limit_watts: float | None = None


class StatusGPUInfo(ApiModel):
    """
    GPU telemetry for every detected device.

    `detected=False`/`devices=()` on any host without a supported GPU
    backend (e.g. no NVIDIA GPU, no driver, or the optional `gpu`
    extra not installed) - this never fails the overall
    `GET /api/v1/status` request.
    """

    detected: bool
    available: bool
    devices: tuple[StatusGPUDeviceInfo, ...] = ()


class StatusTemperatureSensorInfo(ApiModel):
    """A single reported non-GPU thermal sensor reading."""

    label: str
    current_celsius: float
    high_celsius: float | None = None
    critical_celsius: float | None = None


class StatusTemperatureInfo(ApiModel):
    """
    Non-GPU thermal sensor information (CPU/package and any other
    sensor the host platform exposes). GPU temperature is reported
    per-device on `StatusGPUDeviceInfo.temperature_celsius` instead.
    """

    available: bool
    sensors: tuple[StatusTemperatureSensorInfo, ...] = ()


class StatusStorageInfo(ApiModel):
    """
    Filesystem/storage telemetry for the PARIKA workspace (the
    filesystem containing the project root), not every mounted
    filesystem on the host.
    """

    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float


class StatusNetworkInterfaceInfo(ApiModel):
    """Per-interface network counters."""

    name: str
    is_up: bool
    bytes_sent: int
    bytes_received: int


class StatusNetworkInfo(ApiModel):
    """
    Aggregate (and, when available, per-interface) network telemetry.

    `hostname` is redacted the same way as `StatusSystemInfo.hostname`
    (see `api.expose_hostname`).
    """

    available: bool
    hostname: str | None = None
    interface_count: int | None = None
    active_interface_count: int | None = None
    bytes_sent: int | None = None
    bytes_received: int | None = None
    interfaces: tuple[StatusNetworkInterfaceInfo, ...] = ()


class StatusParikaInfo(ApiModel):
    """
    PARIKA-runtime counts/statistics not already exposed as flat
    fields on `StatusResponse` (which retains `lifecycle_state`,
    `execution_state`, `interaction_state`, `overall_health`,
    `active_modules`/`total_modules`, `registered_capabilities`,
    `registered_tools`, `registered_providers`, and `providers`
    unchanged, for backward compatibility).

    Per-session diagnostics (current conversation, last selected
    provider/model, Planner context tokens) are intentionally not
    included here: `GET /api/v1/status` is a stateless snapshot with
    no session context, unlike the `/status` CLI command which reports
    them for the active `InterfaceSession`. See
    docs/guides/Running.md section 12 for this documented limitation.
    """

    version: str
    available_providers: int
    total_models: int
    memory_count: int
    memory_storage_bytes: int
    knowledge_engines: int
    knowledge_sources: int


class StatusResponse(ApiModel):
    uptime_seconds: float
    lifecycle_state: str
    execution_state: str
    interaction_state: str
    overall_health: str
    active_modules: int
    total_modules: int
    registered_capabilities: int
    registered_tools: int
    registered_providers: int
    providers: tuple[StatusProviderSummary, ...] = ()

    system: StatusSystemInfo
    cpu: StatusCPUInfo
    memory: StatusMemoryInfo
    gpu: StatusGPUInfo
    temperature: StatusTemperatureInfo
    storage: StatusStorageInfo
    network: StatusNetworkInfo
    parika: StatusParikaInfo
    timestamp: datetime


class HealthResponse(ApiModel):
    status: str


class ReadyResponse(ApiModel):
    status: str
