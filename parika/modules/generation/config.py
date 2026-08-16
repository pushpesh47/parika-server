"""
PARIKA Generation Module - Configuration

Reads the `[generation]` configuration section: whether the Module is
enabled, and the default output directory used when a Tool caller
does not supply an explicit `output_path` (generation, unlike Vision's
editing Capabilities, usually has no source file to derive a sibling
filename from).

Mirrors `parika.modules.vision.config`'s pattern exactly, minimized to
what this Module actually needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

DEFAULT_ENABLED = True
DEFAULT_OUTPUT_DIRECTORY = "generated"


@dataclass(frozen=True, slots=True, kw_only=True)
class GenerationToolConfig:
    """
    Immutable, typed snapshot of `[generation]` configuration.

    Attributes:
        enabled:
            Whether this Module registers its Capabilities/Tools at
            all.

        output_directory:
            Default directory (relative to `[workspace]
            .default_workspace`, the same base every other
            filesystem-writing Capability already resolves against)
            new artifact files are written under when a caller does
            not supply an explicit `output_path`.
    """

    enabled: bool = DEFAULT_ENABLED
    output_directory: str = DEFAULT_OUTPUT_DIRECTORY


def load_generation_config(
    configuration: Configuration | None,
) -> GenerationToolConfig:
    """
    Build a `GenerationToolConfig` snapshot from `Configuration`.
    """

    if configuration is None:
        return GenerationToolConfig()

    return GenerationToolConfig(
        enabled=bool(configuration.get("generation.enabled", DEFAULT_ENABLED)),
        output_directory=str(
            configuration.get(
                "generation.output_directory", DEFAULT_OUTPUT_DIRECTORY
            )
        ),
    )
