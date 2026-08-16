"""
Unit tests for ResourceManager.

Real `psutil` calls are exercised directly where the sandbox
environment makes the result deterministic enough to assert on
(counts, types). Failure fallbacks are verified by patching the
underlying `psutil`/`socket`/`platform` calls to raise, confirming
`ResourceManager` degrades gracefully rather than propagating.

Hardware-dependent telemetry (GPU, temperature sensors) is mocked
rather than depending on the developer's actual machine, per the
runtime-telemetry testing requirements: tests must not assume any
specific hardware is (or is not) present on the host running them.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from parika.core.configuration.configuration import Configuration
from parika.core.logger.logger import Logger
from parika.core.resource_manager.resource_manager import (
    ResourceManager,
    _safe_percent,
)
from parika.core.resource_manager.resource_status import ResourceStatus


@pytest.fixture
def resource_manager(
    configuration: Configuration,
    logger: Logger,
) -> ResourceManager:
    return ResourceManager(configuration=configuration, logger=logger)


# ---------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------


class TestCpuInfo:
    def test_returns_populated_cpu_info(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        info = resource_manager.get_cpu_info()

        assert isinstance(info.usage_percent, float)
        assert info.logical_core_count > 0

    def test_load_average_and_frequency_are_optional(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        info = resource_manager.get_cpu_info()

        # These are platform-dependent (e.g. `os.getloadavg()` does not
        # exist on Windows); assert only that unavailable values are
        # represented as `None`, never fabricated zeros.
        assert info.load_average_1m is None or isinstance(
            info.load_average_1m, float
        )
        assert info.current_frequency_mhz is None or isinstance(
            info.current_frequency_mhz, float
        )

    def test_falls_back_on_failure(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.psutil.cpu_percent",
            side_effect=RuntimeError("boom"),
        ):
            info = resource_manager.get_cpu_info()

        assert info.usage_percent == 0.0
        assert info.logical_core_count == 0
        assert info.physical_core_count is None
        assert info.load_average_1m is None
        assert info.current_frequency_mhz is None

    def test_missing_load_average_reports_none_not_zero(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.os.getloadavg",
            side_effect=AttributeError("not available on this platform"),
        ):
            info = resource_manager.get_cpu_info()

        assert info.load_average_1m is None
        assert info.load_average_5m is None
        assert info.load_average_15m is None


# ---------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------


class TestMemoryInfo:
    def test_returns_populated_memory_info(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        info = resource_manager.get_memory_info()

        assert info.total_bytes > 0
        assert info.available_bytes >= 0
        assert info.used_bytes >= 0
        assert 0.0 <= info.usage_percent <= 100.0

    def test_falls_back_on_failure(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.psutil.virtual_memory",
            side_effect=RuntimeError("boom"),
        ):
            info = resource_manager.get_memory_info()

        assert info.total_bytes == 0
        assert info.available_bytes == 0
        assert info.used_bytes == 0
        assert info.usage_percent == 0.0
        assert info.free_bytes is None
        assert info.swap_total_bytes is None

    def test_missing_swap_reports_none_not_zero(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.psutil.swap_memory",
            side_effect=RuntimeError("no swap"),
        ):
            info = resource_manager.get_memory_info()

        assert info.total_bytes > 0
        assert info.swap_total_bytes is None
        assert info.swap_used_bytes is None
        assert info.swap_free_bytes is None
        assert info.swap_usage_percent is None


# ---------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------


class TestDiskInfo:
    def test_returns_populated_disk_info_for_project_root(
        self,
        resource_manager: ResourceManager,
        configuration: Configuration,
    ) -> None:
        info = resource_manager.get_disk_info()

        assert info.path == configuration.get_project_root()
        assert info.total_bytes > 0
        assert 0.0 <= info.usage_percent <= 100.0

    def test_falls_back_on_failure(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.psutil.disk_usage",
            side_effect=RuntimeError("boom"),
        ):
            info = resource_manager.get_disk_info()

        assert info.total_bytes == 0
        assert info.free_bytes == 0
        assert info.used_bytes == 0
        assert info.usage_percent == 0.0


# ---------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------


class TestGpuInfo:
    def test_gpu_info_is_conservatively_unknown_without_nvml(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        """
        Exercises the real `ImportError` fallback path end-to-end when
        the optional `pynvml`/`nvidia-ml-py` dependency (the `gpu`
        extra) is not importable - forced deterministically (rather
        than relying on the test machine's actual hardware/dependency
        state, which the `gpu` extra may or may not be installed
        under).
        """

        with patch.dict(sys.modules, {"pynvml": None}):
            info = resource_manager.get_gpu_info()

        assert info.status is ResourceStatus.UNKNOWN
        assert info.detected is False
        assert info.devices == ()

    def test_disabled_via_configuration_reports_unknown(
        self,
        resource_manager: ResourceManager,
        configuration: Configuration,
    ) -> None:
        with patch.object(
            configuration,
            "get",
            side_effect=lambda key, default=None: (
                False if key == "resources.gpu_telemetry_enabled" else default
            ),
        ):
            info = resource_manager.get_gpu_info()

        assert info.status is ResourceStatus.UNKNOWN
        assert info.detected is False
        assert info.devices == ()

    def test_reports_unavailable_when_nvml_finds_no_devices(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        fake_pynvml = _build_fake_pynvml(device_count=0)

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            info = resource_manager.get_gpu_info()

        assert info.status is ResourceStatus.UNAVAILABLE
        assert info.detected is False
        assert info.devices == ()
        assert fake_pynvml.nvmlShutdown.called

    def test_reports_multiple_gpu_devices(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        fake_pynvml = _build_fake_pynvml(device_count=2)

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            info = resource_manager.get_gpu_info()

        assert info.status is ResourceStatus.AVAILABLE
        assert info.detected is True
        assert len(info.devices) == 2

        first = info.devices[0]
        assert first.index == 0
        assert first.name == "Fake GPU"
        assert first.vendor == "NVIDIA"
        assert first.utilization_percent == 42.0
        assert first.memory_total_bytes == 8_000_000_000
        assert first.memory_used_bytes == 4_000_000_000
        assert first.memory_usage_percent == 50.0
        assert first.temperature_celsius == 65.0
        assert first.power_usage_watts == 120.0
        assert first.power_limit_watts == 200.0

    def test_degrades_gracefully_when_a_single_metric_is_unsupported(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        fake_pynvml = _build_fake_pynvml(device_count=1)
        fake_pynvml.nvmlDeviceGetTemperature.side_effect = RuntimeError(
            "NVML_ERROR_NOT_SUPPORTED"
        )

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            info = resource_manager.get_gpu_info()

        assert info.status is ResourceStatus.AVAILABLE
        assert info.devices[0].temperature_celsius is None
        # Every other metric on the same device is still reported.
        assert info.devices[0].name == "Fake GPU"
        assert info.devices[0].utilization_percent == 42.0

    def test_reports_unknown_when_nvml_init_fails(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        fake_pynvml = _build_fake_pynvml(device_count=1)
        fake_pynvml.nvmlInit.side_effect = RuntimeError("driver not loaded")

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            info = resource_manager.get_gpu_info()

        assert info.status is ResourceStatus.UNKNOWN
        assert info.detected is False
        assert info.devices == ()

    def test_reports_unknown_when_device_enumeration_raises(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        fake_pynvml = _build_fake_pynvml(device_count=1)
        fake_pynvml.nvmlDeviceGetCount.side_effect = RuntimeError("backend failure")

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            info = resource_manager.get_gpu_info()

        assert info.status is ResourceStatus.UNKNOWN
        assert info.detected is False
        assert fake_pynvml.nvmlShutdown.called


def _build_fake_pynvml(*, device_count: int) -> types.ModuleType:
    """
    Build a minimal fake `pynvml` module sufficient to exercise every
    `ResourceManager.get_gpu_info()` code path without a real NVIDIA
    GPU or the `nvidia-ml-py` dependency installed.
    """

    module = types.ModuleType("pynvml")
    module.NVML_TEMPERATURE_GPU = 0  # type: ignore[attr-defined]

    module.nvmlInit = MagicMock()  # type: ignore[attr-defined]
    module.nvmlShutdown = MagicMock()  # type: ignore[attr-defined]
    module.nvmlDeviceGetCount = MagicMock(return_value=device_count)  # type: ignore[attr-defined]
    module.nvmlDeviceGetHandleByIndex = MagicMock(  # type: ignore[attr-defined]
        side_effect=lambda index: f"handle-{index}"
    )
    module.nvmlDeviceGetName = MagicMock(return_value="Fake GPU")  # type: ignore[attr-defined]

    utilization = MagicMock()
    utilization.gpu = 42
    module.nvmlDeviceGetUtilizationRates = MagicMock(return_value=utilization)  # type: ignore[attr-defined]

    memory = MagicMock()
    memory.total = 8_000_000_000
    memory.used = 4_000_000_000
    memory.free = 4_000_000_000
    module.nvmlDeviceGetMemoryInfo = MagicMock(return_value=memory)  # type: ignore[attr-defined]

    module.nvmlDeviceGetTemperature = MagicMock(return_value=65)  # type: ignore[attr-defined]
    module.nvmlDeviceGetPowerUsage = MagicMock(return_value=120_000)  # type: ignore[attr-defined]
    module.nvmlDeviceGetEnforcedPowerLimit = MagicMock(return_value=200_000)  # type: ignore[attr-defined]

    return module


# ---------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------


class TestTemperatureInfo:
    def test_reports_sensors_when_available(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        entry = MagicMock()
        entry.label = "Package id 0"
        entry.current = 55.0
        entry.high = 90.0
        entry.critical = 100.0

        with patch(
            "parika.core.resource_manager.resource_manager.psutil.sensors_temperatures",
            create=True,
            return_value={"coretemp": [entry]},
        ):
            info = resource_manager.get_temperature_info()

        assert info.status is ResourceStatus.AVAILABLE
        assert len(info.sensors) == 1
        assert info.sensors[0].label == "coretemp:Package id 0"
        assert info.sensors[0].current_celsius == 55.0
        assert info.sensors[0].high_celsius == 90.0
        assert info.sensors[0].critical_celsius == 100.0

    def test_reports_partial_sensor_data(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        entry = MagicMock()
        entry.label = ""
        entry.current = 40.0
        entry.high = None
        entry.critical = None

        with patch(
            "parika.core.resource_manager.resource_manager.psutil.sensors_temperatures",
            create=True,
            return_value={"acpitz": [entry]},
        ):
            info = resource_manager.get_temperature_info()

        assert info.status is ResourceStatus.AVAILABLE
        assert info.sensors[0].label == "acpitz"
        assert info.sensors[0].high_celsius is None
        assert info.sensors[0].critical_celsius is None

    def test_reports_unavailable_when_no_sensors_are_reported(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.psutil.sensors_temperatures",
            create=True,
            return_value={},
        ):
            info = resource_manager.get_temperature_info()

        assert info.status is ResourceStatus.UNAVAILABLE
        assert info.sensors == ()

    def test_reports_unknown_when_platform_does_not_support_sensors(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        # Simulate Windows/macOS, where `psutil.sensors_temperatures`
        # does not exist at all.
        with patch(
            "parika.core.resource_manager.resource_manager.psutil",
        ) as fake_psutil:
            del fake_psutil.sensors_temperatures

            info = resource_manager.get_temperature_info()

        assert info.status is ResourceStatus.UNKNOWN
        assert info.sensors == ()

    def test_reports_unknown_when_probe_raises(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.psutil.sensors_temperatures",
            create=True,
            side_effect=RuntimeError("boom"),
        ):
            info = resource_manager.get_temperature_info()

        assert info.status is ResourceStatus.UNKNOWN

    def test_disabled_via_configuration_reports_unknown(
        self,
        resource_manager: ResourceManager,
        configuration: Configuration,
    ) -> None:
        with patch.object(
            configuration,
            "get",
            side_effect=lambda key, default=None: (
                False
                if key == "resources.temperature_telemetry_enabled"
                else default
            ),
        ):
            info = resource_manager.get_temperature_info()

        assert info.status is ResourceStatus.UNKNOWN


# ---------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------


class TestNetworkInfo:
    def test_returns_available_when_hostname_resolves(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with (
            patch(
                "parika.core.resource_manager.resource_manager.socket.gethostname",
                return_value="localhost",
            ),
            patch(
                "parika.core.resource_manager.resource_manager.socket.gethostbyname",
                return_value="127.0.0.1",
            ),
        ):
            info = resource_manager.get_network_info()

        assert info.status is ResourceStatus.AVAILABLE
        assert info.hostname == "localhost"
        assert info.interface_count is None or info.interface_count >= 0

    def test_falls_back_to_unavailable_on_failure(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.socket.gethostname",
            side_effect=OSError("boom"),
        ):
            info = resource_manager.get_network_info()

        assert info.status is ResourceStatus.UNAVAILABLE
        assert info.hostname is None

    def test_reports_interface_and_byte_counters(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        up_stat = MagicMock()
        up_stat.isup = True
        down_stat = MagicMock()
        down_stat.isup = False

        aggregate = MagicMock()
        aggregate.bytes_sent = 100
        aggregate.bytes_recv = 200

        per_nic_counters = MagicMock()
        per_nic_counters.bytes_sent = 100
        per_nic_counters.bytes_recv = 200

        with (
            patch(
                "parika.core.resource_manager.resource_manager.psutil.net_if_stats",
                return_value={"eth0": up_stat, "lo": down_stat},
            ),
            patch(
                "parika.core.resource_manager.resource_manager.psutil.net_io_counters",
                side_effect=lambda pernic=False: (
                    {"eth0": per_nic_counters} if pernic else aggregate
                ),
            ),
        ):
            info = resource_manager.get_network_info()

        assert info.interface_count == 2
        assert info.active_interface_count == 1
        assert info.bytes_sent == 100
        assert info.bytes_received == 200
        assert len(info.interfaces) == 1
        assert info.interfaces[0].name == "eth0"
        assert info.interfaces[0].is_up is True

    def test_interface_statistics_failure_does_not_suppress_hostname_status(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with (
            patch(
                "parika.core.resource_manager.resource_manager.socket.gethostname",
                return_value="localhost",
            ),
            patch(
                "parika.core.resource_manager.resource_manager.socket.gethostbyname",
                return_value="127.0.0.1",
            ),
            patch(
                "parika.core.resource_manager.resource_manager.psutil.net_if_stats",
                side_effect=RuntimeError("boom"),
            ),
        ):
            info = resource_manager.get_network_info()

        assert info.status is ResourceStatus.AVAILABLE
        assert info.interface_count is None
        assert info.interfaces == ()


# ---------------------------------------------------------------------
# System
# ---------------------------------------------------------------------


class TestSystemInfo:
    def test_returns_populated_system_info(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        info = resource_manager.get_system_info()

        assert info.platform
        assert info.architecture
        assert info.uptime_seconds is None or info.uptime_seconds >= 0
        assert info.uptime_human is None or ":" in info.uptime_human

    def test_falls_back_on_failure(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        with patch(
            "parika.core.resource_manager.resource_manager.psutil.boot_time",
            side_effect=RuntimeError("boom"),
        ):
            info = resource_manager.get_system_info()

        assert info.boot_time is None
        assert info.uptime_seconds is None
        assert info.uptime_human is None
        # Platform/architecture are stdlib `platform` module calls that
        # do not depend on the failing `psutil.boot_time()` call.
        assert info.platform


# ---------------------------------------------------------------------
# Percentage calculation helper
# ---------------------------------------------------------------------


class TestSafePercent:
    def test_computes_expected_percentage(self) -> None:
        assert _safe_percent(50, 200) == 25.0

    def test_rounds_to_two_decimal_places(self) -> None:
        assert _safe_percent(1, 3) == 33.33

    def test_zero_total_reports_none_not_a_crash(self) -> None:
        assert _safe_percent(10, 0) is None

    def test_negative_total_reports_none(self) -> None:
        assert _safe_percent(10, -5) is None

    def test_missing_values_report_none(self) -> None:
        assert _safe_percent(None, 100) is None
        assert _safe_percent(10, None) is None

    def test_result_is_bounded_between_zero_and_one_hundred(self) -> None:
        # A used value larger than total (e.g. a racy read between two
        # separate syscalls) must never report an out-of-bounds percent.
        assert _safe_percent(150, 100) == 100.0
        assert _safe_percent(-10, 100) == 0.0


# ---------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------


class TestResourceSnapshot:
    def test_snapshot_aggregates_every_resource(
        self,
        resource_manager: ResourceManager,
    ) -> None:
        snapshot = resource_manager.get_resource_snapshot()

        assert snapshot.cpu.logical_core_count >= 0
        assert snapshot.memory.total_bytes >= 0
        assert snapshot.disk.total_bytes >= 0
        assert snapshot.gpu.status in (
            ResourceStatus.AVAILABLE,
            ResourceStatus.UNAVAILABLE,
            ResourceStatus.UNKNOWN,
        )
        assert snapshot.network.status in (
            ResourceStatus.AVAILABLE,
            ResourceStatus.UNAVAILABLE,
        )
        assert len(snapshot.filesystem.paths) == 3
        assert snapshot.temperature.status in (
            ResourceStatus.AVAILABLE,
            ResourceStatus.UNAVAILABLE,
            ResourceStatus.UNKNOWN,
        )
        assert snapshot.system.platform
        assert isinstance(snapshot.timestamp, datetime)
