"""
PARIKA API - Common Schemas

Shared, small building-block schemas reused across multiple domain
schema modules.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """
    Base class for every PARIKA API schema.

    `frozen=True` keeps request/response schemas immutable once
    parsed, matching the immutability convention already used
    throughout PARIKA's Core domain objects -- a stylistic parallel,
    not a functional dependency on Core. `extra="ignore"` (rather than
    "forbid") deliberately favors forward compatibility per the API
    Stability Rules (see `docs/guides/Running.md` section 12.9): a
    client sending a field this version of the server does not yet
    recognize must never fail validation.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")
