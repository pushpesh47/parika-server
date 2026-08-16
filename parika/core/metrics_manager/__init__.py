"""
PARIKA Metrics Manager package.

Provides the MetricsManager component and its primary public
interfaces.
"""

from .exceptions import (
    InvalidMetricNameError,
    InvalidMetricValueError,
    MetricsManagerError,
)
from .metrics_manager import MetricsManager
from .timing_stats import TimingStats

__all__ = [
    "InvalidMetricNameError",
    "InvalidMetricValueError",
    "MetricsManager",
    "MetricsManagerError",
    "TimingStats",
]
