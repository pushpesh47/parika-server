"""
PARIKA Metrics Manager Exceptions

Defines the exception hierarchy used by MetricsManager.

All MetricsManager-specific exceptions derive from
MetricsManagerError.
"""

from __future__ import annotations


class MetricsManagerError(Exception):
    """
    Base exception for all MetricsManager errors.
    """


class InvalidMetricNameError(MetricsManagerError):
    """
    Raised when a metric name is structurally invalid.
    """


class InvalidMetricValueError(MetricsManagerError):
    """
    Raised when a metric value is invalid for the metric being
    recorded.
    """
