"""
PARIKA Module Manifest

Defines the immutable metadata describing a PARIKA Module.

A ModuleManifest describes a module's identity, version, dependencies,
required capabilities, required permissions, configuration schema,
runtime driver, and compatibility information.

The manifest is descriptive only and contains no runtime behavior,
lifecycle management, or business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleManifest:
    """
    Immutable metadata describing a PARIKA Module.

    A ModuleManifest represents the static characteristics of a module
    package. It is descriptive only and does not manage lifecycle,
    execution, registration, or configuration values.
    """

    id: str
    """
    Unique identifier of the module.

    Example:
        filesystem
        web_search
        python_executor
    """

    name: str
    """
    Human-readable module name.

    Example:
        Filesystem
        Web Search
    """

    version: str
    """
    Module version.

    Example:
        1.0.0
    """

    description: str
    """
    Human-readable description of the module.
    """

    author: str
    """
    Module author or organization.
    """

    license: str
    """
    Software license of the module.
    """

    homepage: str | None = None
    """
    Homepage or documentation URL.

    None if unavailable.
    """

    tags: tuple[str, ...] = ()
    """
    Descriptive tags associated with the module.
    """

    dependencies: tuple[str, ...] = ()
    """
    Module identifiers required by this module.

    Dependencies are expressed as module identifiers rather than
    object references.
    """

    required_capabilities: tuple[str, ...] = ()
    """
    Capabilities required for this module to operate.

    These are capability identifiers and are not resolved by the
    ModuleManifest.
    """

    required_permissions: tuple[str, ...] = ()
    """
    Permissions required by this module.

    Permission evaluation is performed by PermissionManager.
    """

    driver: str
    """
    Fully-qualified import path of the ModuleDriver implementation.

    Example:
        parika.modules.filesystem.driver.FilesystemDriver
    """

    configuration_schema: str | None = None
    """
    Identifier of the module configuration schema.

    This references the schema only and does not contain
    configuration values.
    """

    minimum_parika_version: str = "1.0.0"
    """
    Minimum supported PARIKA version.
    """

    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """
    Optional implementation-specific metadata.

    This field may contain presentation or informational metadata
    that does not affect module behavior.
    """

    def __post_init__(self) -> None:
        """
        Guarantee immutability of the metadata mapping.
        """

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )
