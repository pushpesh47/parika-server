"""
PARIKA Experience Module

Records execution outcomes (via ExperienceRecorder, subscribed to
TaskManager's existing events) and exposes an aggregated
historical-success-rate signal through ExperienceStore, which
structurally satisfies Planner's `ExperienceSource` Protocol without
Planner ever importing this package. See
docs/architecture/Intelligence_Foundation_Design.md section 6A.
"""

from .driver import ExperienceModuleDriver
from .exceptions import (
    ExperienceAlreadyExistsError,
    ExperienceError,
    ExperienceNotFoundError,
    ExperiencePersistenceError,
    InvalidExperienceError,
)
from .experience import Experience
from .experience_outcome import ExperienceOutcome
from .experience_store import ExperienceStore
from .manifest import EXPERIENCE_MODULE_ID, create_experience_module
from .recorder import ExperienceRecorder

__all__ = [
    "EXPERIENCE_MODULE_ID",
    "Experience",
    "ExperienceAlreadyExistsError",
    "ExperienceError",
    "ExperienceModuleDriver",
    "ExperienceNotFoundError",
    "ExperienceOutcome",
    "ExperiencePersistenceError",
    "ExperienceRecorder",
    "ExperienceStore",
    "InvalidExperienceError",
    "create_experience_module",
]
