"""
PARIKA Experience Outcome

Defines the supported outcome classifications for a recorded Experience.
"""

from __future__ import annotations

from enum import StrEnum


class ExperienceOutcome(StrEnum):
    """Classification of how an execution (or a user correction) ended."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    USER_CORRECTED = "user_corrected"
