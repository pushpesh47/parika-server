"""
PARIKA AI Context Engineering - Assistant Identity

Owns ONLY building the assistant identity portion of PARIKA's system
prompt: name, nickname, creator/organization attribution, purpose/
description, and version -- derived exclusively from Configuration's
`[assistant]` section (see `config/defaults.toml`).

Owns no behavioral instructions (see `behavior.py`) and no general
constraints (see `constraints.py`); `prompt_builder.py` combines all
three into the final system prompt text.
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration


def build_identity_text(configuration: Configuration) -> str:
    """
    Build the assistant identity sentence(s) from Configuration's
    `[assistant]` section.

    Pure function: reads only the supplied `configuration` argument --
    never a global, never a `ParikaRuntime` -- and always returns the
    same string for the same `Configuration` instance, since
    `Configuration` never changes after `load()` (see
    `Core_Component_Responsibilities.md` - Configuration "Does NOT:
    Modify configuration after loading").

    Adding a new `[assistant]` key (e.g. a future `personality`) only
    ever requires extending this function's body -- never its
    signature, never any caller of it.

    Args:
        configuration:
            The already-loaded Configuration to read `[assistant]`
            values from.

    Returns:
        The composed identity text (name, optional nickname,
        attribution, purpose/description, and version sentences).
    """

    name = configuration.get("assistant.name", "PARIKA")
    nick_name = configuration.get("assistant.nick_name", "")
    full_name = configuration.get("assistant.full_name", "")
    creator = configuration.get("assistant.creator", "")
    organization = configuration.get("assistant.organization", "")
    purpose = configuration.get("assistant.purpose", "")
    description = configuration.get("assistant.description", "")
    version = configuration.get(
        "assistant.version", configuration.get("application.version", "")
    )

    identity_sentence = f"You are {name}"

    if full_name:
        identity_sentence += f" ({full_name})"

    identity_sentence += ", a helpful local-first personal assistant."

    sentences = [identity_sentence]

    if nick_name:
        sentences.append(f"Your nickname is {nick_name}. You are female.")

    attribution = ", ".join(
        part
        for part in (
            f"created by {creator}" if creator else "",
            f"from {organization}" if organization else "",
        )
        if part
    )

    if attribution:
        sentences.append(f"You were {attribution}.")

    purpose_text = purpose or description

    if purpose_text:
        sentences.append(purpose_text)

    if version:
        sentences.append(f"Your current version is {version}.")

    return " ".join(sentences)
