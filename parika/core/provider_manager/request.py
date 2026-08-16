"""
PARIKA Core - ProviderManager Component

Defines the abstract base class for provider requests.

ProviderRequest represents a normalized request sent to a ProviderDriver.
Concrete request types inherit from this class to represent specific AI
operations such as text generation, embeddings, vision, or speech.

ProviderRequest intentionally contains only provider-independent
information shared by every request type.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field

from .options import RequestOptions


@dataclass(frozen=True, slots=True)
class ProviderRequest(ABC):
    """
    Abstract base class for all provider requests.

    Attributes:
        options:
            Provider-independent execution options that control how the
            request should be processed.
    """

    options: RequestOptions = field(default_factory=RequestOptions)