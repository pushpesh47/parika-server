"""
PARIKA Chat Module - Manifest

Defines the static ModuleManifest describing the Chat Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import ChatModuleDriver

CHAT_MODULE_ID = "chat"
CHAT_MODULE_VERSION = "1.0.0"


def create_chat_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Chat Module.
    """

    return ModuleManifest(
        id=CHAT_MODULE_ID,
        name="Chat",
        version=CHAT_MODULE_VERSION,
        description=(
            "Provides the chat.respond Capability: conversational "
            "responses produced by an enabled LLM Provider such as "
            "Ollama."
        ),
        author="PARIKA",
        license="MIT",
        tags=("chat", "llm"),
        driver="parika.modules.chat.driver.ChatModuleDriver",
    )


def create_chat_module(driver: ChatModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Chat Module.

    Args:
        driver:
            Constructed ChatModuleDriver instance for this module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=CHAT_MODULE_ID,
        manifest=create_chat_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
