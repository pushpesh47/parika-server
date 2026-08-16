from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .resource_status import ResourceStatus


@dataclass(frozen=True)
class CPUInfo:
    """Represents the current CPU information."""

    usage_percent: float
    logical_core_count: int
    physical_core_count: int | None
    load_average_1m: float | None = None
    load_average_5m: float | None = None
    load_average_15m: float | None = None
    current_frequency_mhz: float | None = None


@dataclass(frozen=True)
class MemoryInfo:
    """Represents the current host memory (RAM) information."""

    total_bytes: int
    available_bytes: int
    used_bytes: int
    usage_percent: float = 0.0
    free_bytes: int | None = None
    swap_total_bytes: int | None = None
    swap_used_bytes: int | None = None
    swap_free_bytes: int | None = None
    swap_usage_percent: float | None = None


@dataclass(frozen=True)
class DiskInfo:
    """Represents the current disk information for the PARIKA workspace."""

    path: Path
    total_bytes: int
    free_bytes: int
    used_bytes: int
    usage_percent: float = 0.0


@dataclass(frozen=True)
class GPUDeviceInfo:
    """Represents telemetry for a single detected GPU device."""

    index: int
    name: str | None
    vendor: str | None
    utilization_percent: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    memory_free_bytes: int | None = None
    memory_usage_percent: float | None = None
    temperature_celsius: float | None = None
    power_usage_watts: float | None = None
    power_limit_watts: float | None = None


@dataclass(frozen=True)
class GPUInfo:
    """
    Represents the current GPU information across every detected device.

    `status` preserves the pre-existing `ResourceStatus` semantics
    consumed by `Planner`'s model-selection resource filtering
    (`AVAILABLE` when at least one device was detected, `UNAVAILABLE`
    when detection ran but found no GPU, `UNKNOWN` when GPU telemetry
    could not be determined at all, e.g. no NVML backend installed).
    """

    status: ResourceStatus
    detected: bool
    devices: tuple[GPUDeviceInfo, ...] = ()


@dataclass(frozen=True)
class NetworkInterfaceInfo:
    """Represents per-interface network counters."""

    name: str
    is_up: bool
    bytes_sent: int
    bytes_received: int


@dataclass(frozen=True)
class NetworkInfo:
    """Represents the current host network information."""

    status: ResourceStatus
    hostname: str | None
    interface_count: int | None = None
    active_interface_count: int | None = None
    bytes_sent: int | None = None
    bytes_received: int | None = None
    interfaces: tuple[NetworkInterfaceInfo, ...] = ()


@dataclass(frozen=True)
class TemperatureSensorInfo:
    """Represents a single reported thermal sensor reading."""

    label: str
    current_celsius: float
    high_celsius: float | None = None
    critical_celsius: float | None = None


@dataclass(frozen=True)
class TemperatureInfo:
    """
    Represents non-GPU thermal sensor information (CPU/package and any
    other sensor psutil can enumerate on the host platform). GPU
    temperature is reported separately, per device, on `GPUDeviceInfo`.
    """

    status: ResourceStatus
    sensors: tuple[TemperatureSensorInfo, ...] = ()


@dataclass(frozen=True)
class SystemInfo:
    """Represents host operating system and uptime information."""

    platform: str
    operating_system: str
    kernel_release: str | None
    architecture: str
    hostname: str | None
    boot_time: datetime | None
    uptime_seconds: float | None
    uptime_human: str | None


@dataclass(frozen=True)
class FilesystemPathInfo:
    """Represents the accessibility of a filesystem path."""

    path: Path
    exists: bool
    readable: bool
    writable: bool


@dataclass(frozen=True)
class FilesystemInfo:
    """Represents the current filesystem information."""

    status: ResourceStatus
    paths: tuple[FilesystemPathInfo, ...]


@dataclass(frozen=True)
class ResourceSnapshot:
    """Represents a snapshot of the current system resources."""

    cpu: CPUInfo
    memory: MemoryInfo
    disk: DiskInfo
    gpu: GPUInfo
    network: NetworkInfo
    filesystem: FilesystemInfo
    temperature: TemperatureInfo
    system: SystemInfo
    timestamp: datetime
