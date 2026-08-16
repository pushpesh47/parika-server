"""
PARIKA Interfaces - Built-in Slash Commands

Implements every built-in slash command required by the CLI:
`/help`, `/status`, `/config`, `/modules`, `/providers`, `/tools`,
`/capabilities`, `/history`, `/reload`, `/version`, `/clear`,
`/exit`.

Every handler here executes entirely inside the Interface layer. None
of them go through Brain: they read Core managers directly for
read-only introspection, matching the milestone's requirement that
built-in slash commands "execute inside the CLI" and "must NOT go
through Brain".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from parika.interfaces.session import InterfaceSession
from parika.interfaces.history import HistoryRole

from .base import CommandResult, CommandSpec
from .registry import CommandRegistry

PARIKA_VERSION = "0.1.0"

def _handle_about(session: InterfaceSession, args: str) -> CommandResult:
    configuration = session.runtime.configuration

    app_name = configuration.get("application.name", "PARIKA")
    app_version = configuration.get("application.version", "Unknown")
    app_environment = configuration.get("application.environment", "Unknown")

    assistant_name = configuration.get("assistant.name", app_name)
    assistant_full_name = configuration.get("assistant.full_name", "Personal Adaptive Responsive Intelligence Kernel Assistant")
    assistant_nick_name = configuration.get("assistant.nick_name", "PARI")
    assistant_creator = configuration.get("assistant.creator", "Pushpesh")
    assistant_organization = configuration.get("assistant.organization", "Independent")
    assistant_purpose = configuration.get("assistant.purpose", "")
    assistant_description = configuration.get("assistant.description", "")
    assistant_tagline = configuration.get("assistant.tagline", "")
    assistant_website = configuration.get("assistant.website", "")
    assistant_repository = configuration.get("assistant.repository", "")
    assistant_license = configuration.get("assistant.license", "")

    lines = [
        f"{assistant_name} ({assistant_nick_name})",
    ]

    if assistant_full_name:
        lines.append(assistant_full_name)

    lines.extend(
        [
            "",
            f"Version        : {app_version}",
            f"Creator        : {assistant_creator}",
            f"Organization   : {assistant_organization}",
            f"Environment    : {app_environment}",
        ]
    )

    if assistant_tagline:
        lines.extend(
            [
                "",
                "Tagline",
                "-------",
                assistant_tagline,
            ]
        )
        
    if assistant_purpose:
        lines.extend(
            [
                "",
                "Purpose",
                "-------",
                assistant_purpose,
            ]
        )

    if assistant_description:
        lines.extend(
            [
                "",
                "Description",
                "-----------",
                assistant_description,
            ]
        )

    if assistant_repository:
        lines.append(f"Repository     : {assistant_repository}")

    if assistant_website:
        lines.append(f"Website        : {assistant_website}")

    if assistant_license:
        lines.append(f"License        : {assistant_license}")

    return CommandResult(text="\n".join(lines))

def _handle_status(session: InterfaceSession, args: str) -> CommandResult:
    runtime = session.runtime

    uptime = datetime.now(UTC) - runtime.started_at

    lifecycle = runtime.state_manager.get_lifecycle_state()
    execution = runtime.state_manager.get_execution_state()
    interaction = runtime.state_manager.get_interaction_state()

    health_status = runtime.health_manager.overall_status()

    provider_lines = []

    for provider in runtime.provider_manager.get_all():
        health = provider.health
        available = "unknown" if health is None else str(health.available)
        provider_lines.append(
            f"    {provider.id}: enabled={provider.enabled} "
            f"available={available} models={len(provider.models)}"
        )

    active_modules = len(runtime.module_manager.get_active())
    total_modules = len(runtime.module_manager.get_all())

    app_version = runtime.configuration.get("application.version", PARIKA_VERSION)

    lines = [
        f"Version: {app_version}",
        f"Uptime: {uptime}",
        f"Lifecycle state: {lifecycle.value}",
        f"Execution state: {execution.value}",
        f"Interaction state: {interaction.value}",
        f"Overall health: {health_status.value}",
        f"Modules: {active_modules}/{total_modules} active",
        f"Capabilities registered: {len(runtime.capability_registry.get_all())}",
        f"Tools registered: {runtime.tool_manager.count()}",
        f"Providers registered: {runtime.provider_manager.count()}",
        *(["Providers:"] + provider_lines if provider_lines else []),
    ]

    lines.extend(_status_hardware_lines(session))
    lines.extend(_status_intelligence_lines(session))
    lines.extend(_status_voice_lines(session))

    return CommandResult(text="\n".join(lines))


def _status_voice_lines(session: InterfaceSession) -> list[str]:
    """
    Build the Voice preference/availability lines for `/status`:
    current input/output language preference, configured English/
    Hindi voice labels, and STT/TTS availability -- read exclusively
    from the same shared `VoiceLanguagePreferenceStore`/
    `[providers.local_speech]` configuration/`ProviderManager` state
    the Voice API's `GET /voice/settings` endpoint reports, never a
    second source of truth.

    Never fails `/status` if the Voice Module/registry is unavailable
    (e.g. `[voice].enabled = false`) -- reports "N/A" instead.
    """

    runtime = session.runtime

    try:
        from parika.modules.voice.language import VoiceLanguagePreferenceStore
        from parika.providers.local_speech.config import load_local_speech_config

        preference_store = runtime.service_container.get(
            VoiceLanguagePreferenceStore
        )
        preference = preference_store.get()
        local_speech_config = load_local_speech_config(runtime.configuration)
    except Exception:  # noqa: BLE001 - Voice is optional; never break /status
        return ["Voice:", "  N/A (Voice Module unavailable)"]

    stt_available = False
    tts_available = False

    for provider in runtime.provider_manager.get_all():
        if provider.id != "provider.local_speech":
            continue

        for model in provider.models:
            if "speech_to_text" in model.specializations:
                stt_available = True
            if "text_to_speech" in model.specializations:
                tts_available = True

    english_voice = (
        local_speech_config.tts_voice
        if local_speech_config.tts_model_path
        else "not configured"
    )
    hindi_voice = (
        local_speech_config.tts_hindi_voice
        if local_speech_config.tts_hindi_model_path
        else "not configured"
    )

    return [
        "Voice:",
        f"  Input language: {preference.input_language.value}",
        f"  Output language: {preference.output_language.value}",
        f"  English voice: {english_voice}",
        f"  Hindi voice: {hindi_voice}",
        f"  STT: {'Available' if stt_available else 'Unavailable'}",
        f"  TTS: {'Available' if tts_available else 'Unavailable'}",
    ]


def _format_bytes(value: int | float | None) -> str:
    """
    Render a raw byte count as a short human-readable string (e.g.
    "16.9 GiB"), or "N/A" when the value is unavailable. Purely a CLI
    presentation concern - the underlying `ResourceManager`/API
    telemetry always carries the exact raw byte count as well.
    """

    if value is None:
        return "N/A"

    size = float(value)

    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024.0 or unit == "PiB":
            return f"{size:.1f} {unit}"
        size /= 1024.0

    return f"{size:.1f} PiB"  # pragma: no cover - unreachable in practice


def _format_percent(value: float | None) -> str:
    """Render a percentage, or "N/A" when the value is unavailable."""

    return "N/A" if value is None else f"{value:.1f}%"


def _format_optional(value: object, *, suffix: str = "") -> str:
    """Render an optional scalar value, or "N/A" when unavailable."""

    return "N/A" if value is None else f"{value}{suffix}"


def _status_hardware_lines(session: InterfaceSession) -> list[str]:
    """
    Build the System/CPU/RAM/GPU/Temperature/Storage/Network runtime
    telemetry lines for `/status`, sourced exclusively from
    `ResourceManager.get_resource_snapshot()` - one on-demand read per
    `/status` invocation, exactly like every other existing caller of
    `ResourceManager`. Every value that cannot be determined on the
    current host is rendered as "N/A", never a fabricated zero.
    """

    runtime = session.runtime
    snapshot = runtime.resource_manager.get_resource_snapshot()

    lines = [
        "System:",
        f"  Platform: {snapshot.system.platform}",
        f"  Architecture: {snapshot.system.architecture}",
        f"  Uptime: {snapshot.system.uptime_human or 'N/A'}",
        "CPU:",
        f"  Usage: {_format_percent(snapshot.cpu.usage_percent)}",
        f"  Logical CPUs: {snapshot.cpu.logical_core_count}",
        f"  Physical CPUs: {_format_optional(snapshot.cpu.physical_core_count)}",
        (
            "  Load: "
            + (
                "N/A"
                if snapshot.cpu.load_average_1m is None
                else (
                    f"{snapshot.cpu.load_average_1m:.2f} / "
                    f"{snapshot.cpu.load_average_5m:.2f} / "
                    f"{snapshot.cpu.load_average_15m:.2f}"
                )
            )
        ),
        "RAM:",
        f"  Usage: {_format_percent(snapshot.memory.usage_percent)}",
        f"  Used: {_format_bytes(snapshot.memory.used_bytes)}",
        f"  Available: {_format_bytes(snapshot.memory.available_bytes)}",
        f"  Total: {_format_bytes(snapshot.memory.total_bytes)}",
    ]

    if not snapshot.gpu.devices:
        lines.append("GPU:")
        lines.append("  No GPU detected.")
    else:
        lines.append("GPU:")

        for device in snapshot.gpu.devices:
            lines.append(f"  {device.name or f'GPU {device.index}'}")
            lines.append(
                f"    Utilization: {_format_percent(device.utilization_percent)}"
            )
            lines.append(
                "    VRAM: "
                f"{_format_bytes(device.memory_used_bytes)} / "
                f"{_format_bytes(device.memory_total_bytes)} "
                f"({_format_percent(device.memory_usage_percent)})"
            )
            lines.append(
                f"    Temperature: {_format_optional(device.temperature_celsius, suffix='°C')}"
            )

    if snapshot.temperature.sensors:
        lines.append("Temperature:")

        for sensor in snapshot.temperature.sensors:
            lines.append(f"  {sensor.label}: {sensor.current_celsius:.1f}°C")

    lines.extend(
        [
            "Storage:",
            f"  {snapshot.disk.path}",
            f"  Usage: {_format_percent(snapshot.disk.usage_percent)}",
            f"  Free: {_format_bytes(snapshot.disk.free_bytes)}",
            "Network:",
            f"  RX: {_format_bytes(snapshot.network.bytes_received)}",
            f"  TX: {_format_bytes(snapshot.network.bytes_sent)}",
        ]
    )

    return lines


def _status_intelligence_lines(session: InterfaceSession) -> list[str]:
    """
    Build the Memory/Knowledge/Experience/Session/Planner diagnostic
    lines for `/status` (Phase 1 Completion Specification section 18).

    "Loaded this request"/"Memory hits"/"Knowledge hits"/"Experience
    hits"/"Context tokens"/"Advertised tools"/"Selected provider"/
    "Selected model" are per-request diagnostics from the most
    recently submitted chat turn (`InterfaceSession.
    last_turn_diagnostics`); they are unavailable (reported as such,
    never fabricated) before the first turn.
    """

    runtime = session.runtime
    memory_stats = runtime.memory_manager.stats()
    diagnostics = session.last_turn_diagnostics

    lines = [
        "Memory:",
        f"  Permanent memories: {memory_stats.total}",
        f"  Loaded this request: {diagnostics.memory_hits if diagnostics else 'n/a'}",
        f"  Memory hits: {diagnostics.memory_hits if diagnostics else 'n/a'}",
        "Knowledge:",
        f"  Knowledge engines: {runtime.knowledge_manager.count_engines()}",
        f"  Indexed documents: {runtime.knowledge_manager.count_sources()}",
        f"  Knowledge hits: {diagnostics.knowledge_hits if diagnostics else 'n/a'}",
        "Experience:",
        (
            "  Experience hits: "
            + (
                "n/a"
                if diagnostics is None or diagnostics.experience_success_rate is None
                else f"{diagnostics.experience_success_rate:.2f}"
            )
        ),
        "Session:",
        f"  Current messages: {diagnostics.conversation_message_count if diagnostics else 'n/a'}",
        f"  Conversation tokens: {diagnostics.conversation_tokens if diagnostics else 'n/a'}",
        "Planner:",
        f"  Context tokens: {diagnostics.context_tokens if diagnostics else 'n/a'}",
        (
            "  Advertised tools: "
            + (", ".join(diagnostics.advertised_tools) or "none" if diagnostics else "n/a")
        ),
        f"  Selected provider: {(diagnostics.selected_provider if diagnostics else None) or 'n/a'}",
        f"  Selected model: {(diagnostics.selected_model if diagnostics else None) or 'n/a'}",
    ]

    return lines


def _handle_config(session: InterfaceSession, args: str) -> CommandResult:
    configuration = session.runtime.configuration.all()

    if args:
        value = session.runtime.configuration.get(args)
        return CommandResult(text=f"{args} = {json.dumps(value, default=str)}")

    return CommandResult(
        text=json.dumps(configuration, indent=2, default=str, sort_keys=True)
    )


def _handle_modules(session: InterfaceSession, args: str) -> CommandResult:
    modules = session.runtime.module_manager.get_all()

    if not modules:
        return CommandResult(text="No modules registered.")

    lines = ["Modules:"]

    for module in sorted(modules, key=lambda item: item.id):
        lines.append(
            f"  {module.id:<16} v{module.manifest.version:<8} "
            f"state={module.state.value}"
        )

    return CommandResult(text="\n".join(lines))


def _handle_providers(session: InterfaceSession, args: str) -> CommandResult:
    providers = session.runtime.provider_manager.get_all()

    if not providers:
        return CommandResult(text="No providers registered.")

    lines = ["Providers:"]

    for provider in sorted(providers, key=lambda item: item.id):
        health = provider.health
        available = "unknown" if health is None else str(health.available)
        lines.append(
            f"  {provider.id:<20} enabled={provider.enabled} "
            f"state={provider.state.value} available={available} "
            f"models={len(provider.models)}"
        )

        for model in sorted(provider.models, key=lambda item: item.id):
            capabilities = ", ".join(sorted(c.value for c in model.capabilities))
            lines.append(f"      - {model.id} [{capabilities}]")

    return CommandResult(text="\n".join(lines))


def _handle_tools(session: InterfaceSession, args: str) -> CommandResult:
    tools = session.runtime.tool_manager.get_all()

    if not tools:
        return CommandResult(text="No tools registered.")

    lines = ["Tools:"]

    for tool in sorted(tools, key=lambda item: item.id):
        capabilities = ", ".join(tool.capabilities)
        lines.append(
            f"  {tool.id:<20} v{tool.version:<8} enabled={tool.enabled} "
            f"capabilities=[{capabilities}]"
        )

    return CommandResult(text="\n".join(lines))


def _handle_capabilities(session: InterfaceSession, args: str) -> CommandResult:
    definitions = session.runtime.capability_registry.get_all()

    if not definitions:
        return CommandResult(text="No capabilities registered.")

    lines = ["Capabilities:"]

    for definition in sorted(definitions, key=lambda item: item.id):
        lines.append(
            f"  {definition.id:<20} category={definition.category.value:<12} "
            f"enabled={definition.enabled}"
        )

    return CommandResult(text="\n".join(lines))


def _handle_history(session: InterfaceSession, args: str) -> CommandResult:
    entries = session.history()

    if not entries:
        return CommandResult(text="No history yet.")

    lines = []

    for entry in entries:
        timestamp = entry.created_at.strftime("%H:%M:%S")
        lines.append(f"[{timestamp}] {entry.role.value}: {entry.text}")

    return CommandResult(text="\n".join(lines))


def _handle_reload(session: InterfaceSession, args: str) -> CommandResult:
    """
    Reload every active Module, then re-run model discovery and a
    health refresh for every registered Provider ("provider
    reconnect") - useful after starting Ollama (or any other
    Provider) *after* PARIKA itself, since discovery otherwise only
    ever runs once, at startup.

    Provider-agnostic: this never assumes Ollama specifically, and a
    Provider that fails to reconnect is reported without aborting the
    rest of the reload.
    """

    module_manager = session.runtime.module_manager
    provider_manager = session.runtime.provider_manager

    reloaded_modules = []

    for module in module_manager.get_active():
        module_manager.unload(module.id)
        module_manager.load(module.id)
        reloaded_modules.append(module.id)

    reconnected_providers: list[str] = []
    failed_providers: list[str] = []

    for provider in provider_manager.get_all():
        try:
            provider_manager.discover_models(provider.id)
            provider_manager.refresh_health(provider.id)
            reconnected_providers.append(provider.id)
        except Exception as ex:  # noqa: BLE001 - best-effort reconnect
            failed_providers.append(f"{provider.id} ({ex})")

    lines = []

    if reloaded_modules:
        lines.append(
            "Reloaded modules: " + ", ".join(sorted(reloaded_modules))
        )
    else:
        lines.append("No active modules to reload.")

    if reconnected_providers:
        lines.append(
            "Reconnected providers: "
            + ", ".join(sorted(reconnected_providers))
        )

    if failed_providers:
        lines.append(
            "Providers still unavailable: " + ", ".join(failed_providers)
        )

    return CommandResult(text="\n".join(lines))


def _handle_version(session: InterfaceSession, args: str) -> CommandResult:
    configuration = session.runtime.configuration

    app_name = configuration.get("application.name", "PARIKA")
    app_version = configuration.get("application.version", PARIKA_VERSION)

    return CommandResult(
        text=f"{app_name} v{app_version} (CLI interface v{PARIKA_VERSION})"
    )


def _handle_clear(session: InterfaceSession, args: str) -> CommandResult:
    session.clear()

    return CommandResult(text="", should_clear_screen=True)


def _handle_sessions(session: InterfaceSession, args: str) -> CommandResult:
    """
    Dispatch `/sessions list|resume <id>|search <query>`.

    A no-op-reporting command (not an error) when this session has no
    `session_store` configured, since session persistence is opt-in.
    """

    store = session.session_store

    if store is None:
        return CommandResult(text="Session persistence is not enabled for this session.")

    parts = args.strip().split(maxsplit=1)
    subcommand = parts[0].lower() if parts else "list"
    remainder = parts[1] if len(parts) > 1 else ""

    if subcommand == "list":
        summaries = InterfaceSession.list_sessions(store)

        if not summaries:
            return CommandResult(text="No saved sessions yet.")

        lines = ["Saved sessions:"]
        for summary in summaries:
            title = summary.title or "(untitled)"
            lines.append(
                f"  {summary.session_id}  {title}  "
                f"({summary.message_count} messages, updated {summary.updated_at:%Y-%m-%d %H:%M})"
            )

        return CommandResult(text="\n".join(lines))

    if subcommand == "resume":
        if not remainder:
            return CommandResult(text="Usage: /sessions resume <id>")

        from parika.interfaces.session_store import SessionNotFoundError

        try:
            resumed = InterfaceSession.load(remainder, session.runtime, store)

        except SessionNotFoundError as ex:
            return CommandResult(text=str(ex))

        return CommandResult(
            text=f"Resumed session '{remainder}'.", new_session=resumed
        )

    if subcommand == "search":
        if not remainder:
            return CommandResult(text="Usage: /sessions search <query>")

        matches = store.search_messages(remainder, limit=10)

        if not matches:
            return CommandResult(text="No matching messages found.")

        lines = ["Matching messages:"]
        for message in matches:
            snippet = message.content[:100].replace("\n", " ")
            lines.append(f"  [{message.session_id}] {message.role}: {snippet}")

        return CommandResult(text="\n".join(lines))

    if subcommand == "rename":
        rename_parts = remainder.split(maxsplit=1)

        if len(rename_parts) != 2:
            return CommandResult(text="Usage: /sessions rename <id> <new title>")

        from parika.interfaces.session_store import SessionNotFoundError

        session_id, new_title = rename_parts

        try:
            store.set_title(session_id, new_title)
        except SessionNotFoundError as ex:
            return CommandResult(text=str(ex))

        return CommandResult(text=f"Renamed session '{session_id}' to '{new_title}'.")

    if subcommand == "delete":
        if not remainder:
            return CommandResult(text="Usage: /sessions delete <id>")

        deleted = store.delete_session(remainder)

        if not deleted:
            return CommandResult(text=f"Session '{remainder}' was not found.")

        return CommandResult(text=f"Deleted session '{remainder}'.")

    if subcommand == "export":
        export_parts = remainder.split(maxsplit=1)

        if not export_parts:
            return CommandResult(text="Usage: /sessions export <id> [path]")

        from pathlib import Path

        from parika.interfaces.session_store import SessionNotFoundError

        target_session_id = export_parts[0]
        export_path = (
            Path(export_parts[1])
            if len(export_parts) > 1
            else Path.cwd()
            / f"parika_session_{target_session_id}_{datetime.now(UTC):%Y%m%d_%H%M%S}.json"
        )

        try:
            count = store.export_session(target_session_id, path=export_path)
        except SessionNotFoundError as ex:
            return CommandResult(text=str(ex))

        return CommandResult(
            text=f"Exported {count} messages from session '{target_session_id}' to '{export_path}'."
        )

    if subcommand == "import":
        if not remainder:
            return CommandResult(text="Usage: /sessions import <path>")

        from pathlib import Path

        from parika.interfaces.session_store import SessionPersistenceError

        try:
            imported_id = store.import_session(path=Path(remainder))
        except SessionPersistenceError as ex:
            return CommandResult(text=str(ex))

        return CommandResult(text=f"Imported session as '{imported_id}'.")

    return CommandResult(
        text=(
            f"Unknown /sessions subcommand '{subcommand}'. Use list, resume, "
            "rename, delete, export, import, or search."
        )
    )


def _handle_memory(session: InterfaceSession, args: str) -> CommandResult:
    """
    Dispatch `/memory [list]|search <query>|delete <id>|clear [confirm]|
    stats|export [path]|import <path>` (Phase 1 Completion
    Specification section 10). Bare `/memory` behaves like
    `/memory list`.
    """

    memory_manager = session.runtime.memory_manager

    parts = args.strip().split(maxsplit=1)
    subcommand = parts[0].lower() if parts else "list"
    remainder = parts[1].strip() if len(parts) > 1 else ""

    if subcommand == "list":
        memories = memory_manager.list(limit=50)

        if not memories:
            return CommandResult(text="No permanent memories yet.")

        return CommandResult(text=_format_memories(memories))

    if subcommand == "search":
        if not remainder:
            return CommandResult(text="Usage: /memory search <query>")

        from parika.core.memory_manager.memory_search_query import MemorySearchQuery

        results = memory_manager.search(MemorySearchQuery(text=remainder, limit=20))

        if not results:
            return CommandResult(text="No matching memories found.")

        return CommandResult(text=_format_memories([r.memory for r in results]))

    if subcommand == "delete":
        if not remainder:
            return CommandResult(text="Usage: /memory delete <id>")

        from parika.core.memory_manager.exceptions import MemoryNotFoundError

        try:
            removed = memory_manager.forget(remainder)
        except MemoryNotFoundError as ex:
            return CommandResult(text=str(ex))

        return CommandResult(text=f"Deleted memory '{removed.memory_id}'.")

    if subcommand == "clear":
        count = memory_manager.count()

        if remainder.lower() != "confirm":
            return CommandResult(
                text=(
                    f"This will permanently delete all {count} memories. "
                    "Run '/memory clear confirm' to proceed."
                )
            )

        cleared = memory_manager.clear()

        return CommandResult(text=f"Cleared {len(cleared)} memories.")

    if subcommand == "stats":
        stats = memory_manager.stats()

        lines = [
            "Memory statistics:",
            f"  Permanent memories: {stats.total}",
            f"  Storage size: {stats.storage_size_bytes} bytes",
            "  By category:",
        ]
        for category, count in sorted(stats.by_category.items()):
            lines.append(f"    {category}: {count}")

        lines.append("  By importance:")
        for importance, count in sorted(stats.by_importance.items()):
            lines.append(f"    {importance}: {count}")

        return CommandResult(text="\n".join(lines))

    if subcommand == "export":
        from pathlib import Path

        export_path = (
            Path(remainder)
            if remainder
            else Path.cwd() / f"parika_memory_export_{datetime.now(UTC):%Y%m%d_%H%M%S}.json"
        )

        count = memory_manager.export(export_path)

        return CommandResult(text=f"Exported {count} memories to '{export_path}'.")

    if subcommand == "import":
        if not remainder:
            return CommandResult(text="Usage: /memory import <path>")

        from pathlib import Path

        from parika.core.memory_manager.exceptions import MemoryPersistenceError

        try:
            count = memory_manager.import_memories(Path(remainder))
        except MemoryPersistenceError as ex:
            return CommandResult(text=str(ex))

        return CommandResult(text=f"Imported {count} memories from '{remainder}'.")

    return CommandResult(
        text=(
            f"Unknown /memory subcommand '{subcommand}'. Use list, search, "
            "delete, clear, stats, export, or import."
        )
    )


def _format_memories(memories) -> str:
    lines = ["Permanent memories:"]

    for memory in memories:
        lines.append(
            f"  [{memory.memory_id}] category={memory.category.value} "
            f"importance={memory.importance.value} confidence={memory.confidence:.2f} "
            f"source={memory.origin.value}\n"
            f"      {memory.content}\n"
            f"      created={memory.created_at:%Y-%m-%d %H:%M} "
            f"updated={memory.updated_at:%Y-%m-%d %H:%M}"
        )

    return "\n".join(lines)


def _handle_exit(session: InterfaceSession, args: str) -> CommandResult:
    return CommandResult(text="Session ended.", should_exit=True)


def create_default_registry() -> CommandRegistry:
    """
    Build the registry of every built-in slash command.
    """

    registry = CommandRegistry()

    def _handle_help(session: InterfaceSession, args: str) -> CommandResult:
        lines = ["Available commands:"]

        for spec in registry.list_specs():
            lines.append(f"  /{spec.name:<12} {spec.description}")

        return CommandResult(text="\n".join(lines))

    registry.register(
        CommandSpec(
            name="about",
            description="Show information about the assistant and application.",
            handler=_handle_about,
        )
    )
    registry.register(
        CommandSpec(
            name="help",
            description="List available commands.",
            handler=_handle_help,
        )
    )
    registry.register(
        CommandSpec(
            name="status",
            description="Show runtime, health, and provider status.",
            handler=_handle_status,
        )
    )
    registry.register(
        CommandSpec(
            name="config",
            description=(
                "Show configuration (optionally a single dotted key)."
            ),
            handler=_handle_config,
        )
    )
    registry.register(
        CommandSpec(
            name="modules",
            description="List registered Modules and their state.",
            handler=_handle_modules,
        )
    )
    registry.register(
        CommandSpec(
            name="providers",
            description="List registered Providers and their models.",
            handler=_handle_providers,
        )
    )
    registry.register(
        CommandSpec(
            name="tools",
            description="List registered Tools.",
            handler=_handle_tools,
        )
    )
    registry.register(
        CommandSpec(
            name="capabilities",
            description="List registered Capabilities.",
            handler=_handle_capabilities,
        )
    )
    registry.register(
        CommandSpec(
            name="history",
            description="Show this session's conversation history.",
            handler=_handle_history,
        )
    )
    registry.register(
        CommandSpec(
            name="reload",
            description=(
                "Reload active Modules and reconnect every Provider "
                "(re-run model discovery and a health refresh)."
            ),
            handler=_handle_reload,
        )
    )
    registry.register(
        CommandSpec(
            name="version",
            description="Show the PARIKA and CLI interface version.",
            handler=_handle_version,
        )
    )
    registry.register(
        CommandSpec(
            name="clear",
            description="Clear the screen and this session's history.",
            handler=_handle_clear,
        )
    )
    registry.register(
        CommandSpec(
            name="exit",
            description="End the session.",
            handler=_handle_exit,
        )
    )
    registry.register(
        CommandSpec(
            name="sessions",
            description=(
                "Manage saved sessions: list, resume <id>, rename <id> <title>, "
                "delete <id>, export <id> [path], import <path>, or search <query>."
            ),
            handler=_handle_sessions,
        )
    )
    registry.register(
        CommandSpec(
            name="memory",
            description=(
                "Manage permanent memory: list, search <query>, delete <id>, "
                "clear [confirm], stats, export [path], or import <path>."
            ),
            handler=_handle_memory,
        )
    )

    return registry
