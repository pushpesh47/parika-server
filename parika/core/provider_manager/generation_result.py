"""
PARIKA Core - ProviderManager Component

Defines the provider-independent generation result type.

`GenerationResult` is the generic analogue of a concrete generation
provider's own response (e.g. ComfyUI's history/queue payload): the
normalized outcome of one generative media operation that every
provider-independent layer (Modules) consumes, with no provider-
specific wire concept. The Provider selected by Planner produces this
from its own concrete response at the provider boundary
(`ProviderDriver.execute()` for a `GenerationRequest`), exactly like
every other `ProviderResponse` subtype (see `ChatResult` for the
established pattern this type mirrors).

Never carries a provider's raw execution/queue metadata (e.g.
ComfyUI's history JSON, node data, or queue ids) -- only the produced
artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass

from .response import ProviderResponse


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratedArtifact:
    """
    Immutable, provider-independent representation of one piece of
    generated media.

    Attributes:
        content_base64:
            Base64-encoded artifact bytes, in the same provider-
            independent shape as `ChatMessage.images`.

        mime_type:
            IANA media type of the artifact (e.g. `"image/png"`,
            `"video/mp4"`), so callers can determine how to interpret
            and persist `content_base64` without any provider-specific
            knowledge.
    """

    content_base64: str
    mime_type: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GenerationResult(ProviderResponse):
    """
    Provider-independent outcome of one generative media operation.

    Attributes:
        artifacts:
            Every artifact produced by this operation, in provider-
            reported order. Most operations produce exactly one
            artifact; a provider that produces several (e.g. a
            candidate grid) returns all of them here.
    """

    artifacts: tuple[GeneratedArtifact, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
