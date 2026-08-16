"""
PARIKA Interfaces - Slash Commands.

Slash commands execute inside the Interface layer and never go
through Brain.
"""

from .base import CommandHandler, CommandResult, CommandSpec
from .builtin import create_default_registry
from .registry import CommandRegistry

__all__ = [
    "CommandHandler",
    "CommandRegistry",
    "CommandResult",
    "CommandSpec",
    "create_default_registry",
]
