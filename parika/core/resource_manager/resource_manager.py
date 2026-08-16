from __future__ import annotations

import os
import platform
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import psutil

from parika.core.configuration.configuration import Configuration
from parika.core.logger.logger import Logger

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
from .resource_status import ResourceStatus

_T = TypeVar("_T")


class ResourceManager:
    """
    Provides on-demand access to the current system resource information.

    Every method below performs a fresh, synchronous read of the host
    (via `psutil`, the standard library, and - for GPU telemetry - the
    optional NVIDIA NVML backend) each time it is called. Nothing is
    cached, nothing is monitored continuously, and nothing is
    published to the `EventBus`: callers (`Planner`, the `/status` CLI
    command, and the `GET /api/v1/status` API handler) each decide for
    themselves how often to ask for a snapshot.
    """

    def __init__(
        self,
        configuration: Configuration,
        logger: Logger,
    ) -> None:
        """
        Initialize the resource manager.

        Args:
            configuration:
                Loaded application configuration.

            logger:
                Shared logger service.
        """

        self._configuration = configuration
        self._logger = logger.get_logger(__name__)

    def get_cpu_info(self) -> CPUInfo:
        """
        Return the current CPU information.
        """

        try:
            usage_percent = psutil.cpu_percent(interval=None)
            logical_core_count = psutil.cpu_count(logical=True) or 0
            physical_core_count = psutil.cpu_count(logical=False)

            load_average_1m: float | None = None
            load_average_5m: float | None = None
            load_average_15m: float | None = None

            try:
                load_average_1m, load_average_5m, load_average_15m = (
                    os.getloadavg()
                )
            except (AttributeError, OSError):
                # `os.getloadavg()` is not available on every platform
                # (notably Windows) - reported as unavailable, not zero.
                pass

            current_frequency_mhz: float | None = None

            try:
                frequency = psutil.cpu_freq()

                if frequency is not None:
                    current_frequency_mhz = frequency.current
            except Exception:
                # Some sandboxed/virtualized hosts raise here even
                # though `cpu_freq` exists - degrade gracefully.
                pass

            return CPUInfo(
                usage_percent=usage_percent,
                logical_core_count=logical_core_count,
                physical_core_count=physical_core_count,
                load_average_1m=load_average_1m,
                load_average_5m=load_average_5m,
                load_average_15m=load_average_15m,
                current_frequency_mhz=current_frequency_mhz,
            )

        except Exception:
            self._logger.exception("Failed to retrieve CPU information.")

            return CPUInfo(
                usage_percent=0.0,
                logical_core_count=0,
                physical_core_count=None,
            )

    def get_memory_info(self) -> MemoryInfo:
        """
        Return the current host memory (RAM) information.
        """

        try:
            memory = psutil.virtual_memory()

            swap_total_bytes: int | None = None
            swap_used_bytes: int | None = None
            swap_free_bytes: int | None = None
            swap_usage_percent: float | None = None

            try:
                swap = psutil.swap_memory()
                swap_total_bytes = swap.total
                swap_used_bytes = swap.used
                swap_free_bytes = swap.free
                swap_usage_percent = swap.percent
            except Exception:
                # Swap is not guaranteed to exist/be readable on every
                # platform - reported as unavailable, not zero.
                pass

            return MemoryInfo(
                total_bytes=memory.total,
                available_bytes=memory.available,
                used_bytes=memory.used,
                usage_percent=memory.percent,
                free_bytes=getattr(memory, "free", None),
                swap_total_bytes=swap_total_bytes,
                swap_used_bytes=swap_used_bytes,
                swap_free_bytes=swap_free_bytes,
                swap_usage_percent=swap_usage_percent,
            )

        except Exception:
            self._logger.exception("Failed to retrieve memory information.")

            return MemoryInfo(
                total_bytes=0,
                available_bytes=0,
                used_bytes=0,
                usage_percent=0.0,
            )

    def get_disk_info(self) -> DiskInfo:
        """
        Return information about the filesystem containing the PARIKA project.
        """

        try:
            project_root = self._configuration.get_project_root()
            usage = psutil.disk_usage(str(project_root))

            return DiskInfo(
                path=project_root,
                total_bytes=usage.total,
                free_bytes=usage.free,
                used_bytes=usage.used,
                usage_percent=usage.percent,
            )

        except Exception:
            self._logger.exception("Failed to retrieve disk information.")

            project_root = self._configuration.get_project_root()

            return DiskInfo(
                path=project_root,
                total_bytes=0,
                free_bytes=0,
                used_bytes=0,
                usage_percent=0.0,
            )

    def get_gpu_info(self) -> GPUInfo:
        """
        Return the current GPU information for every detected device.

        Uses the optional NVIDIA NVML backend (`nvidia-ml-py`, the
        `gpu` extra) when it is installed and enabled via
        `resources.gpu_telemetry_enabled`. NVML is never required for
        PARIKA to start or run: on any import failure, initialization
        failure, or platform without an NVML-compatible GPU, this
        degrades to `status=UNKNOWN`/`UNAVAILABLE` rather than raising.
        No non-NVIDIA GPU backend is implemented; this makes no
        hardware-vendor assumption in the data model (`GPUInfo`/
        `GPUDeviceInfo` are vendor-neutral), only in this collection
        strategy.
        """

        if not self._configuration.get("resources.gpu_telemetry_enabled", True):
            return GPUInfo(status=ResourceStatus.UNKNOWN, detected=False)

        try:
            import pynvml
        except ImportError:
            return GPUInfo(status=ResourceStatus.UNKNOWN, detected=False)

        try:
            pynvml.nvmlInit()
        except Exception:
            return GPUInfo(status=ResourceStatus.UNKNOWN, detected=False)

        try:
            device_count = pynvml.nvmlDeviceGetCount()

            if device_count == 0:
                return GPUInfo(status=ResourceStatus.UNAVAILABLE, detected=False)

            devices = tuple(
                self._read_nvml_device(pynvml, index)
                for index in range(device_count)
            )

            return GPUInfo(
                status=ResourceStatus.AVAILABLE,
                detected=True,
                devices=devices,
            )

        except Exception:
            self._logger.exception("Failed to enumerate GPU devices.")

            return GPUInfo(status=ResourceStatus.UNKNOWN, detected=False)

        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    def _read_nvml_device(self, pynvml: Any, index: int) -> GPUDeviceInfo:
        """
        Read one NVML device's telemetry.

        Every individual metric is read defensively: a driver/device
        that does not support a given metric (`NVMLError_NotSupported`
        and friends) must not prevent every other metric from being
        reported.
        """

        handle = pynvml.nvmlDeviceGetHandleByIndex(index)

        name = self._safe_nvml_call(lambda: pynvml.nvmlDeviceGetName(handle))

        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")

        utilization = self._safe_nvml_call(
            lambda: pynvml.nvmlDeviceGetUtilizationRates(handle)
        )
        utilization_percent = (
            float(utilization.gpu) if utilization is not None else None
        )

        memory = self._safe_nvml_call(
            lambda: pynvml.nvmlDeviceGetMemoryInfo(handle)
        )
        memory_total_bytes = int(memory.total) if memory is not None else None
        memory_used_bytes = int(memory.used) if memory is not None else None
        memory_free_bytes = int(memory.free) if memory is not None else None
        memory_usage_percent = _safe_percent(
            memory_used_bytes, memory_total_bytes
        )

        temperature = self._safe_nvml_call(
            lambda: pynvml.nvmlDeviceGetTemperature(
                handle, pynvml.NVML_TEMPERATURE_GPU
            )
        )
        temperature_celsius = (
            float(temperature) if temperature is not None else None
        )

        power_usage_milliwatts = self._safe_nvml_call(
            lambda: pynvml.nvmlDeviceGetPowerUsage(handle)
        )
        power_usage_watts = (
            power_usage_milliwatts / 1000.0
            if power_usage_milliwatts is not None
            else None
        )

        power_limit_milliwatts = self._safe_nvml_call(
            lambda: pynvml.nvmlDeviceGetEnforcedPowerLimit(handle)
        )
        power_limit_watts = (
            power_limit_milliwatts / 1000.0
            if power_limit_milliwatts is not None
            else None
        )

        return GPUDeviceInfo(
            index=index,
            name=name,
            vendor="NVIDIA",
            utilization_percent=utilization_percent,
            memory_total_bytes=memory_total_bytes,
            memory_used_bytes=memory_used_bytes,
            memory_free_bytes=memory_free_bytes,
            memory_usage_percent=memory_usage_percent,
            temperature_celsius=temperature_celsius,
            power_usage_watts=power_usage_watts,
            power_limit_watts=power_limit_watts,
        )

    def _safe_nvml_call(self, call: Callable[[], _T]) -> _T | None:
        """
        Invoke a single NVML query, swallowing per-metric failures.
        """

        try:
            return call()
        except Exception:
            return None

    def get_temperature_info(self) -> TemperatureInfo:
        """
        Return non-GPU thermal sensor information when the host
        platform exposes it.

        `psutil.sensors_temperatures()` is Linux-only; on every other
        platform (and when disabled via
        `resources.temperature_telemetry_enabled`) this reports
        `UNKNOWN` rather than fabricating sensor data. Sensor names are
        never hardcoded - whatever groups/labels the platform reports
        are surfaced as-is.
        """

        if not self._configuration.get(
            "resources.temperature_telemetry_enabled", True
        ):
            return TemperatureInfo(status=ResourceStatus.UNKNOWN)

        sensors_temperatures = getattr(psutil, "sensors_temperatures", None)

        if sensors_temperatures is None:
            return TemperatureInfo(status=ResourceStatus.UNKNOWN)

        try:
            readings = sensors_temperatures()

        except Exception:
            self._logger.exception(
                "Failed to retrieve temperature sensor information."
            )

            return TemperatureInfo(status=ResourceStatus.UNKNOWN)

        if not readings:
            return TemperatureInfo(status=ResourceStatus.UNAVAILABLE)

        sensors: list[TemperatureSensorInfo] = []

        for group_name, entries in readings.items():
            for entry in entries:
                label = f"{group_name}:{entry.label}" if entry.label else group_name

                sensors.append(
                    TemperatureSensorInfo(
                        label=label,
                        current_celsius=float(entry.current),
                        high_celsius=(
                            float(entry.high) if entry.high is not None else None
                        ),
                        critical_celsius=(
                            float(entry.critical)
                            if entry.critical is not None
                            else None
                        ),
                    )
                )

        return TemperatureInfo(status=ResourceStatus.AVAILABLE, sensors=tuple(sensors))

    def get_network_info(self) -> NetworkInfo:
        """
        Return host network information.

        Hostname resolution (whether the local hostname resolves to an
        address) preserves the pre-existing `status`/`hostname`
        semantics. Interface counts and byte counters are additive and
        collected independently, so a hostname-resolution failure does
        not suppress interface telemetry.
        """

        try:
            hostname = socket.gethostname()

            socket.gethostbyname(hostname)

            status = ResourceStatus.AVAILABLE

        except Exception:
            self._logger.exception("Failed to retrieve network information.")

            hostname = None
            status = ResourceStatus.UNAVAILABLE

        interface_count: int | None = None
        active_interface_count: int | None = None
        bytes_sent: int | None = None
        bytes_received: int | None = None
        interfaces: tuple[NetworkInterfaceInfo, ...] = ()

        try:
            interface_stats = psutil.net_if_stats()
            interface_count = len(interface_stats)
            active_interface_count = sum(
                1 for stat in interface_stats.values() if stat.isup
            )

            aggregate = psutil.net_io_counters()

            if aggregate is not None:
                bytes_sent = aggregate.bytes_sent
                bytes_received = aggregate.bytes_recv

            if self._configuration.get("resources.network_interfaces_enabled", True):
                per_interface = psutil.net_io_counters(pernic=True)

                interfaces = tuple(
                    NetworkInterfaceInfo(
                        name=name,
                        is_up=(
                            interface_stats[name].isup
                            if name in interface_stats
                            else False
                        ),
                        bytes_sent=counters.bytes_sent,
                        bytes_received=counters.bytes_recv,
                    )
                    for name, counters in per_interface.items()
                )

        except Exception:
            self._logger.exception(
                "Failed to retrieve network interface statistics."
            )

        return NetworkInfo(
            status=status,
            hostname=hostname,
            interface_count=interface_count,
            active_interface_count=active_interface_count,
            bytes_sent=bytes_sent,
            bytes_received=bytes_received,
            interfaces=interfaces,
        )

    def get_system_info(self) -> SystemInfo:
        """
        Return host operating system, architecture, and uptime information.
        """

        try:
            boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=UTC)
            uptime_seconds = (datetime.now(UTC) - boot_time).total_seconds()
            uptime_human = str(timedelta(seconds=max(0, round(uptime_seconds))))

            return SystemInfo(
                platform=platform.system(),
                operating_system=platform.platform(),
                kernel_release=platform.release() or None,
                architecture=platform.machine(),
                hostname=socket.gethostname(),
                boot_time=boot_time,
                uptime_seconds=uptime_seconds,
                uptime_human=uptime_human,
            )

        except Exception:
            self._logger.exception("Failed to retrieve system information.")

            return SystemInfo(
                platform=platform.system(),
                operating_system=platform.platform(),
                kernel_release=None,
                architecture=platform.machine(),
                hostname=None,
                boot_time=None,
                uptime_seconds=None,
                uptime_human=None,
            )

    def get_filesystem_info(self) -> FilesystemInfo:
        """
        Return accessibility information for configured PARIKA directories.
        """

        try:
            project_root = self._configuration.get_project_root()

            configured_directories = (
                self._configuration.get("logging.directory", "logs"),
                self._configuration.get("data.directory", "data"),
                self._configuration.get("plugins.directory", "plugins"),
            )

            paths: list[FilesystemPathInfo] = []

            for directory in configured_directories:

                path = project_root / directory

                exists = path.exists()
                is_directory = path.is_dir() if exists else False

                paths.append(
                    FilesystemPathInfo(
                        path=path,
                        exists=exists,
                        readable=exists and is_directory and os.access(path, os.R_OK),
                        writable=exists and is_directory and os.access(path, os.W_OK),
                    )
                )

            status = (
                ResourceStatus.AVAILABLE
                if all(
                    path.exists
                    and path.readable
                    and path.writable
                    for path in paths
                )
                else ResourceStatus.UNAVAILABLE
            )

            return FilesystemInfo(
                status=status,
                paths=tuple(paths),
            )

        except Exception:
            self._logger.exception("Failed to retrieve filesystem information.")

            return FilesystemInfo(
                status=ResourceStatus.UNKNOWN,
                paths=(),
            )

    def get_resource_snapshot(self) -> ResourceSnapshot:
        """
        Return a snapshot of the current system resources.
        """

        return ResourceSnapshot(
            cpu=self.get_cpu_info(),
            memory=self.get_memory_info(),
            disk=self.get_disk_info(),
            gpu=self.get_gpu_info(),
            network=self.get_network_info(),
            filesystem=self.get_filesystem_info(),
            temperature=self.get_temperature_info(),
            system=self.get_system_info(),
            timestamp=datetime.now(UTC),
        )


def _safe_percent(used: int | None, total: int | None) -> float | None:
    """
    Compute a bounded `0-100` usage percentage from raw byte counts.

    Returns `None` (never a fabricated `0.0`) when either value is
    unavailable, and `None` rather than raising or returning `inf`/
    `nan` when `total` is zero or negative.
    """

    if used is None or total is None or total <= 0:
        return None

    percent = (used / total) * 100

    return round(min(max(percent, 0.0), 100.0), 2)
