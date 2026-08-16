"""
Resource management subsystem.

Provides on-demand access to system resource information, including CPU,
memory, disk, GPU, temperature, network, host/system information, and
complete resource snapshots.
"""

from .models import (
    CPUInfo,
    DiskInfo,
    FilesystemInfo,
    FilesystemPathInfo,
    GPUDeviceInfo,
    GPUInfo,
    MemoryInfo,
    NetworkInfo,
    NetworkInterfaceInfo,
    ResourceSnapshot,
    SystemInfo,
    TemperatureInfo,
    TemperatureSensorInfo,
)
from .resource_manager import ResourceManager
from .resource_status import ResourceStatus

__all__ = [
    "CPUInfo",
    "DiskInfo",
    "FilesystemInfo",
    "FilesystemPathInfo",
    "GPUDeviceInfo",
    "GPUInfo",
    "MemoryInfo",
    "NetworkInfo",
    "NetworkInterfaceInfo",
    "ResourceSnapshot",
    "SystemInfo",
    "TemperatureInfo",
    "TemperatureSensorInfo",
    "ResourceManager",
    "ResourceStatus",
]
