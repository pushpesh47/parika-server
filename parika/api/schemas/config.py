"""
PARIKA API - Configuration Schemas

`Configuration` is read-only, loaded once per process, by design (see
`docs/architecture/Core_Component_Responsibilities.md` section 1) --
`/api/v1/config` mirrors that: it never accepts a write, exactly like
the existing `/config` slash command.
"""

from __future__ import annotations

from typing import Any

from .common import ApiModel


class ConfigResponse(ApiModel):
    key: str | None = None
    value: Any = None


class ReloadResponse(ApiModel):
    reloaded_modules: tuple[str, ...] = ()
    reconnected_providers: tuple[str, ...] = ()
    failed_providers: tuple[str, ...] = ()
