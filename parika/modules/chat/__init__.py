"""
PARIKA Chat Module.

Registers the `chat.respond` Capability, routed to an enabled LLM
Provider (e.g. the Ollama provider) for conversational responses.
"""

from .driver import CHAT_CAPABILITY_ID, ChatModuleDriver
from .manifest import (
    CHAT_MODULE_ID,
    create_chat_module,
    create_chat_module_manifest,
)

__all__ = [
    "CHAT_CAPABILITY_ID",
    "CHAT_MODULE_ID",
    "ChatModuleDriver",
    "create_chat_module",
    "create_chat_module_manifest",
]
