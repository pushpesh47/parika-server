# Running PARIKA

**Status:** Reference documentation for installing, configuring, and starting PARIKA.

------------------------------------------------------------------------

# 1. Requirements

- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`
- Internet access (optional) — required only by network-facing Modules and Tools such as the Web Search, Weather, Currency, and News Modules
- [Ollama](https://ollama.com) (optional) — required only to exercise local model tool-calling against PARIKA capabilities

------------------------------------------------------------------------

# 2. Installation

From the repository root:

```bash
uv venv .venv
uv pip install -e .
uv pip install -e ".[dev]"
```

Or with plain `pip`:

```bash
python3.14 -m venv .venv
. .venv/bin/activate
pip install -e .
pip install -e ".[dev]"
```

The `dev` extra installs `pytest`, used by the test suite described in
[`Testing.md`](Testing.md).

------------------------------------------------------------------------

# 3. Dependencies

Runtime dependencies (see `pyproject.toml`):

- `psutil` — used by `ResourceManager` for CPU, memory, and disk information.
- `tomlkit` — used by `Configuration` to parse layered TOML configuration files.

PARIKA follows a **Standard Library First** policy (see the Coding Standards).
The Web Search Tool, for example, performs all HTTP, retry, and HTML parsing
using only `urllib`, `html.parser`, and other standard library modules —
no additional HTTP client or HTML parsing dependency is required.

------------------------------------------------------------------------

# 4. Configuration

Configuration is loaded and merged by the `Configuration` Core component from
layered TOML files under `config/`, in order of increasing precedence:

```text
config/defaults.toml       (required)
config/installation.toml   (optional)
config/workspace.toml      (optional)
config/environment.toml    (optional)
config/runtime.toml        (optional)
```

Higher layers override lower layers. `defaults.toml` ships with the project
and should not be edited; add overrides to `installation.toml`,
`workspace.toml`, `environment.toml`, or `runtime.toml` instead.

Relevant default keys:

```toml
[logging]
level = "INFO"
directory = "logs"
file = "parika.log"

[data]
directory = "data"

[plugins]
directory = "plugins"
autoload = true

[modules]
autoload = true
```

`Configuration` locates the project root by walking upward from its own file
location until it finds `pyproject.toml`, so PARIKA can be run from any
working directory.

------------------------------------------------------------------------

# 5. Bootstrapping and Startup

PARIKA does not currently ship a single `main` entry point; the Core is
composed explicitly by wiring components together with constructor
injection, in the order defined by
[`../architecture/PARIKA_Architecture_Specification_v1.0.md`](../architecture/PARIKA_Architecture_Specification_v1.0.md)
section 5.1 ("Core Implementation Order"). A minimal bootstrap that starts
Brain, TaskManager, and the Web Search Module looks like this:

```python
from parika.core.brain.brain import Brain
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.web_search.driver import WebSearchModuleDriver
from parika.modules.web_search.manifest import (
    WEB_SEARCH_MODULE_ID,
    create_web_search_module,
)

configuration = Configuration()
configuration.load()

logger = Logger(configuration)
event_bus = EventBus(logger=logger)

capability_registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
capability_resolver = CapabilityResolver(capability_registry=capability_registry, logger=logger)
resource_manager = ResourceManager(configuration=configuration, logger=logger)
policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
tool_manager = ToolManager(event_bus=event_bus, logger=logger)
module_manager = ModuleManager(configuration=configuration, event_bus=event_bus, logger=logger)

capability_executor = CapabilityExecutor(
    event_bus=event_bus, logger=logger,
    tool_manager=tool_manager, provider_manager=provider_manager,
)
task_manager = TaskManager(event_bus=event_bus, logger=logger, capability_executor=capability_executor)
planner = Planner(
    capability_resolver=capability_resolver, resource_manager=resource_manager,
    policy_engine=policy_engine, provider_manager=provider_manager,
    tool_manager=tool_manager, logger=logger,
)
brain = Brain(planner=planner, task_manager=task_manager, logger=logger)

module_driver = WebSearchModuleDriver(
    capability_registry=capability_registry, tool_manager=tool_manager, logger=logger,
)
module_manager.register(create_web_search_module(module_driver))
module_manager.load(WEB_SEARCH_MODULE_ID)
```

Once wired, submit work to Brain with a `BrainRequest`:

```python
from parika.core.brain.brain_request import BrainRequest
from parika.core.planner.goal import Goal

goal = Goal(id="search-1", capability_id="web.search", inputs={"query": "PARIKA architecture"})
response = brain.handle(BrainRequest(goals=(goal,)))

print(response.succeeded)
for result in response.results:
    print(result.goal_id, result.status, result.succeeded)
```

`Brain.handle()` never raises for planning or execution failures; inspect
`response.succeeded`, `response.planning_failure`, and each `GoalResult` to
determine what happened.

------------------------------------------------------------------------

# 6. Running with a Local Ollama Model

To let a local Ollama model decide to call `web.search`, expose the
capability as a tool in the model's chat request, then feed the resulting
tool call into Brain as a `Goal`:

```python
import json
import urllib.request

payload = {
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Search the web for PARIKA architecture."}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and return relevant results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    }],
    "stream": False,
}

request = urllib.request.Request(
    "http://localhost:11434/api/chat",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(request, timeout=120) as response:
    body = json.loads(response.read())

call = body["message"]["tool_calls"][0]["function"]
goal = Goal(id="ollama-call", capability_id="web.search", inputs=call["arguments"])
brain_response = brain.handle(BrainRequest(goals=(goal,)))
```

This exact flow — `Ollama → Brain → Planner → TaskManager →
CapabilityExecutor → ToolManager → Web Search Tool → Internet` — has been
verified against a real, locally running Ollama instance (`qwen3:8b`). The
model correctly decides to call `web_search` with a well-formed query, and
PARIKA correctly plans, executes, and reports the result through every Core
component with no shortcuts.

**Note on network environments:** every HTML-scraping Web Search Tool
backend (`search_backend_google.py`, `search_backend_bing.py`,
`search_backend_duckduckgo.py`, `search_backend_mojeek.py`,
`search_backend_qwant.py`) scrapes that provider's no-API-key HTML
endpoint. Some networks — particularly datacenter and shared cloud IP
ranges — are served an anti-bot/CAPTCHA challenge page instead of results.
PARIKA detects this condition and raises a clear `WebSearchNetworkError`
rather than silently returning zero results, and automatically falls over
to the next configured provider (see below) rather than failing the search
outright. Because `SearchBackend` is a small protocol (see
[`Tool_Guide.md`](../development/Tool_Guide.md) §18), operators affected by
this can also supply an entirely custom backend (e.g. a self-hosted SearXNG
instance) to the `WebSearchModuleDriver` without changing any other Core or
Module code.

**Multi-provider failover:** `config/defaults.toml`'s `[web_search]`
section (`enabled`, `default_provider`, `provider_order`, plus
`[web_search.google_cse]` for the one provider that needs credentials)
configures a `FailoverSearchBackend` across every implemented provider -
`google` (the default), `bing`, `duckduckgo`, `mojeek`, `qwant`, and
`google_cse` (see [`Tool_Guide.md`](../development/Tool_Guide.md) §18).
`default_provider` is tried first; if it errors, times out, is served an
anti-bot/CAPTCHA challenge, returns an HTTP error, or returns a malformed
response, each remaining configured, *available* provider is tried in turn
until one succeeds, or a clean `WebSearchAllProvidersFailedError` is raised
once every available provider has failed. `google_cse` is automatically
skipped - never attempted - until `[web_search.google_cse].api_key` and
`.search_engine_id` are both configured. This is purely additive — a
`WebSearchModuleDriver` constructed with an explicit `search_backend` (as
most existing embedding code and tests do) is entirely unaffected.

**Result selection and ranking:** `WebSearchToolDriver` requests a
generous candidate pool from the configured provider
(`[web_search].candidate_pool_size`, default 20) - not just the final
requested count - ranks it by relevance to the query
(`[web_search].ranking_enabled`, on by default), and only then
truncates to `[web_search].default_max_results` (default 10, or an
explicit `max_results` tool-call argument). This is what prevents a
relevant result that happened to appear near the end of a provider's
own raw order from ever being silently discarded by truncation; see
[`Tool_Guide.md`](../development/Tool_Guide.md) §20.

**No hardcoded years:** the Web Search Tool's own `query` parameter
contract (`WEB_SEARCH_TOOL_AFFORDANCE` in `parika/tools/web_search/
manifest.py` -- discovered generically by AI Context Engineering's
`ai_context.tool_context`, never defined there) explicitly instructs
the model to preserve any year the user mentioned verbatim, never
invent or assume one, and to call `get_current_datetime` first if it
needs today's date to resolve a relative timeframe (e.g. "this week")
- PARIKA never injects a year into the query itself, since the Tool
only ever receives whatever query text the model itself decided to
send.

------------------------------------------------------------------------

# 7. Logs

Logs are written to `logs/parika.log` (configurable via `logging.directory`
and `logging.file`) and mirrored to the console. If the log directory or
file cannot be created, PARIKA falls back to console-only logging rather
than failing to start.

**Quieting the console while using the CLI interactively:** the console and
file handlers share the same configured `logging.level` (see
[`PARIKA_Core_Coding_Standards.md`](../architecture/PARIKA_Core_Coding_Standards.md)
— Logger only configures the logging system, it never decides what should be
logged per consumer). The example configuration shipped in
`config/environment.toml` sets `logging.level = "DEBUG"`, which is useful
while developing but noisy for interactive CLI use. To get a quiet console
while using the CLI, set a higher level (e.g. `WARNING`) in
`config/workspace.toml` or `config/runtime.toml` — being higher-precedence
layers, they override `environment.toml` without editing it:

```toml
# config/workspace.toml
[logging]
level = "WARNING"
```

File logging at `logs/parika.log` is unaffected by which layer sets the
level; only the *value* changes for both handlers together.

------------------------------------------------------------------------

# 8. The PARIKA Console

PARIKA ships a production interactive Console (`parika/console/`,
formerly `parika/interfaces/cli/`) built on the reusable Interface
abstraction in `parika/interfaces/` (see
[`Core_Component_Responsibilities.md`](../architecture/Core_Component_Responsibilities.md)
and the Interface Architecture described below). The Console is
PARIKA's native, in-process administration console -- not an external
client, and never routed through `/api/v1` (see section 12.7). The
same `ParikaRuntime`/`InterfaceSession` abstractions it is built on are
designed to support future external clients (a future REST-backed
Desktop UI, Web UI, or Voice interface) without any change to Brain,
even though those future clients will reach Brain through `/api/v1`
rather than in-process like the Console does.

## 8.1 Interface Architecture

```text
parika/interfaces/
├── runtime.py       ParikaRuntime + build_default_runtime() (composition root)
├── session.py       InterfaceSession: session lifecycle, request parsing,
│                     submits BrainRequests to Brain, interprets responses
├── chat_capability.py  Builds the chat.respond Goal + tool specifications
├── history.py       HistoryEntry / HistoryRole
├── commands/         Slash-command parsing and built-in commands
│                     (execute directly against Core managers; never call Brain)
└── formatting/       Presentation-neutral response/error formatting

parika/console/
├── app.py            CliApplication + main() — the native PARIKA Console:
│                     REPL, banner, streaming dispatch
├── colors.py         ANSI helpers
├── markdown.py       Terminal Markdown renderer
├── streaming.py      StreamingPrinter — token sink
├── progress_view.py  ConsoleProgressRenderer — live execution-progress
│                     rendering (Phase 3.5b, see section 12.7 below)
└── workspace_permission_prompt.py  Concrete WorkspacePermissionPrompt
```

`parika/console/` (formerly `parika/interfaces/cli/`) is the only
package that is terminal-specific; everything under `parika/interfaces/`
remains shared, reusable Interface infrastructure. See section 12.7
below for why the Console is permanently separate from the API layer.

`ParikaRuntime` is a typed bundle of already-constructed Core singletons
(`Configuration`, `Logger`, `EventBus`, `CapabilityRegistry`,
`ProviderManager`, `ToolManager`, `ModuleManager`, `Brain`, and so on),
produced by `build_default_runtime()` in the Core Implementation Order
mandated by section 5.1 of the Architecture Specification. Every concrete
Interface is constructed against one `ParikaRuntime`.

Normal user text always becomes a `BrainRequest` submitted to
`runtime.brain.handle()` — the Interface layer never resolves capabilities,
selects providers/tools, or executes anything itself. Built-in slash
commands (`/status`, `/providers`, `/tools`, `/modules`, `/capabilities`,
`/config`, `/history`, `/reload`, `/version`, `/help`, `/clear`, `/exit`)
execute entirely inside the Interface layer instead: they read other Core
managers directly for read-only introspection and intentionally never call
Brain, matching their purely informational/administrative nature.

## 8.2 Running the CLI

Both of the following are equivalent and start the same interactive REPL:

```bash
parika
python -m parika
```

```text
$ parika
PARIKA v0.1.0
Type /help for commands, or start chatting. Ctrl+D to exit.

> Hello
Hello! How can I help you today?

> Search the web for the latest PARIKA architecture news
[used tool `web_search` - ok]
Here is a summary of what I found... (with citations from the search results)

> /status
Uptime: 0:03:12.441021
Lifecycle state: stopped
Execution state: idle
Interaction state: idle
Overall health: unknown
Modules: 2/2 active
Capabilities registered: 2
Tools registered: 1
Providers registered: 1
Providers:
    provider.ollama: enabled=True available=True models=5

> /exit
Goodbye.
```

Features:

- **History and arrow-key navigation** — provided by the standard library
  `readline` module (imported automatically when available). Input history
  additionally persists across runs to the file configured by
  `interfaces.cli.history_file` (default `data/cli_history`).
- **Multiline input** — end a line with a trailing backslash (`\`) to
  continue on the next line; the CLI shows a `... ` continuation prompt
  until a line without a trailing backslash is entered.
- **Markdown output** — headings, bullet/ordered lists, fenced code blocks,
  and inline `**bold**`/`*italic*`/`` `code` `` spans are rendered for the
  terminal (`parika/console/markdown.py`). Disable with
  `interfaces.cli.markdown = false`.
- **Terminal colors** — ANSI colors are used for the banner, prompt,
  headings, and inline formatting when connected to a real terminal.
  Disable with `interfaces.cli.color = false`; colors are also
  automatically disabled when stdout is not a TTY (e.g. when piping
  output).
- **Streaming** — the model's final answer is printed token by token as it
  is generated (see section 8.3). Disable with `interfaces.cli.stream =
  false` to wait for the full response instead.
- **Graceful `Ctrl+C`** — cancels the current input line and returns to the
  prompt without exiting.
- **Graceful `Ctrl+D`** — ends the session cleanly (equivalent to `/exit`).

## 8.3 Streaming and Tool Calling

Normal text is turned into a `Goal` targeting the `chat.respond` Capability
(registered by the Chat Module, category `LLM`), with a
`provider_request_builder` that constructs an `OllamaChatRequest` carrying:

- The full rolling conversation history for the session (so multi-turn
  context is preserved).
- Every enabled `TOOL`-category Capability, advertised as a callable
  function (`parika/interfaces/chat_capability.py`).
- An `on_token` callback that the CLI wires to print each streamed
  fragment immediately (`parika/console/streaming.py`).

`Planner` selects an enabled Provider exposing a `TEXT_GENERATION` model —
today, the Ollama provider — exactly as described in
[`PARIKA_Decision_Flow.md`](../architecture/PARIKA_Decision_Flow.md) section
4.4. When the selected model decides to call a tool (e.g. `web_search`),
`OllamaProviderDriver` resolves it by calling `Brain.handle()` with a new
`Goal` targeting the mapped Capability id — **never** by invoking
`ToolManager` directly — so capability resolution, policy evaluation, and
Tool/Provider selection all still go through Planner exactly as they would
for any other request. The tool's result is fed back to the model as a
`tool`-role chat message, and the conversation continues (up to
`providers.ollama.max_tool_iterations` round trips) until the model produces
a final answer with no further tool calls. This exact flow — CLI → Brain →
Planner → TaskManager → CapabilityExecutor → ProviderManager →
`OllamaProviderDriver` → Brain (again, for the tool call) → Planner →
TaskManager → CapabilityExecutor → ToolManager → Web Search Tool → Internet
→ back up through every layer to the model → CLI — is exercised end to end
in `tests/integration/test_chat_pipeline.py` and has additionally been
verified against a real, locally running Ollama instance (`qwen3:8b`) and
the real internet.

**Streamed output is always plain assistant text, never provider
protocol:** some model templates occasionally leak their raw tool-call
markup (e.g. `<function=...>`) into streamed content instead of using
Ollama's native `tool_calls` field. `OllamaProviderDriver` withholds any
such markup from `on_token` live, in real time, rather than only stripping
it after the fact — the CLI itself performs no filtering of its own; see
[`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md) §11.1.
A tool-calling turn's message also never carries leftover displayable
content (§11.2), so exactly one assistant response is ever streamed or
recorded per user turn, even across multiple tool round trips.

**Repeated tool failures are not re-executed:** if the model calls the
same tool with the exact same arguments again after that exact call
already failed, the cached failure is fed back directly instead of
executing the tool a second time (§11.3) — a genuinely different set of
arguments always executes normally.

## 8.4 Ollama Configuration

The Ollama provider is registered automatically by `build_default_runtime()`
and reads its configuration entirely from TOML — no base URL, timeout, or
model name is ever hardcoded:

```toml
# config/defaults.toml
[providers.ollama]
enabled = true
base_url = "http://127.0.0.1:11434"
connect_timeout_seconds = 5.0
request_timeout_seconds = 120.0
max_tool_iterations = 5
default_model = ""
```

Override any of these in `config/installation.toml`, `config/workspace.toml`,
`config/environment.toml`, or `config/runtime.toml` (higher layers win).
Setting `providers.ollama.enabled = false` skips Ollama registration
entirely; PARIKA still starts normally, with `chat.respond` simply
unavailable until a Provider is registered.

**No hardcoded model names:** `OllamaProviderDriver.list_models()` calls
Ollama's own `GET /api/tags` and `POST /api/show` endpoints to discover
every installed model and derive its `ModelCapability`/
`ModelExecutionFeature`/`ModelLimits` from what Ollama itself reports
(`parika/providers/ollama/model_mapping.py`), so any Ollama-compatible model
— `qwen`, `llama`, `mistral`, `deepseek`, `glm`, or otherwise — works
without code changes the moment it is `ollama pull`-ed.

**Graceful degradation:** if Ollama is not installed, not running, or a
specific model is missing, `build_default_runtime()` logs a warning and
continues starting normally rather than failing; `chat.respond` requests
made before Ollama becomes available fail with a clear planning failure
(`NoAvailableProviderModelError`) reported through the normal
`BrainResponse`/`ChatTurnResult` error path, exactly like any other
unsatisfiable capability.

**Provider reconnect:** run `/reload` once Ollama becomes reachable — it
now re-runs model discovery and a health refresh for every registered
Provider (in addition to reloading active Modules), so a full CLI restart
is no longer required:

```text
> /reload
Reloaded modules: chat, runtime_info, web_search
Reconnected providers: provider.ollama
```

If a Provider still cannot be reached, `/reload` reports it without
failing the rest of the command: `Providers still unavailable:
provider.ollama (...)`.

## 8.5 Interactive Chat and Tool-Calling Example (real Ollama)

The following was captured against a real, locally running Ollama instance
(`qwen3:8b`), reproducing the same verified flow described in section 6:

```text
> Use the web_search tool to search for: current PARIKA architecture kernel.
[used tool `web_search` - failed]
The search for "current PARIKA architecture kernel" returned an error,
which may indicate the term is unclear, misspelled, or unrelated to known
technologies...
```

(The search failed here only because the sandboxed network used to capture
this example is served DuckDuckGo's anti-bot challenge page instead of
results — see section 6's note on network environments. The model still
correctly decided to call `web_search`, PARIKA correctly routed the call
through Brain and Planner to the real Web Search Tool, and the failure was
fed back to the model, which produced a coherent, honest answer instead of
hallucinating search results.)

------------------------------------------------------------------------

# 9. Intelligent Model Selection

When more than one Provider model can satisfy a request, Planner no
longer just picks the first match — it scores every enabled, available
candidate against configurable weights and preferences, and logs the
full decision. See
[`Model_Selection_Framework.md`](../architecture/Model_Selection_Framework.md)
for the complete design; this section covers day-to-day configuration.

## 9.1 Configuration

Everything lives under `[model_selection]` in `config/defaults.toml`
(override in a higher-precedence layer such as `config/workspace.toml`
or `config/runtime.toml` — never edit `defaults.toml` itself):

```toml
[model_selection.weights]
latency = 40
reasoning = 25
tool_calling = 20
context_window = 10
cost = 5

[model_selection.preferences]
prefer_local = true
prefer_streaming = true
prefer_healthier_provider = true
prefer_lower_latency = true
prefer_larger_context = false

[model_selection.reasoning]
simple = "off"
normal = "auto"
complex = "on"
```

No code change is ever required to tune these values. A weight for a
dimension you have not configured simply falls back to its built-in
default (matching the values shown above), never to an error.

## 9.2 Thinking Mode

`[model_selection.reasoning]` maps how much reasoning a request needs
(`simple`/`normal`/`complex`, derived automatically from the
Capability's category, e.g. `REASONING`/`PLANNING` default to
`complex`) to whether the selected model should be asked to "think"
(`off`/`auto`/`on`). `auto` means no explicit preference is sent — the
model's own default behavior applies. If you find a model still thinks
more than you want even under `auto` (some reasoning-tuned models
default to thinking on regardless), set the relevant entry to `"off"`
explicitly:

```toml
[model_selection.reasoning]
normal = "off"
```

Providers that do not support a reasoning toggle simply ignore this
preference; for Ollama, it becomes the native `think` request field.

## 9.3 Seeing Every Decision

With the default logging configuration (`logging.level = "DEBUG"`,
`model_selection.log_decision = true`), every selection logs the
requirements it evaluated, every candidate considered (accepted with its
full score breakdown, or rejected with a reason), and the final choice:

```text
DEBUG parika.core.planner.planner Model selection requirements: capability=text_generation reasoning_level=normal tool_calling=preferred streaming_required=False min_context_window=None
DEBUG parika.core.planner.planner Candidate provider=provider.ollama model=deepseek-r1:14b score=81.19 breakdown=[latency=27.12, reasoning=20.00, tool_calling=20.00, context_window=4.07, cost=5.00, prefer_local=5.00, prefer_streaming=0.00, prefer_healthier_provider=0.00]
DEBUG parika.core.planner.planner Candidate provider=provider.ollama model=qwen3-coder:latest score=105.00 breakdown=[latency=40.00, reasoning=25.00, tool_calling=20.00, context_window=10.00, cost=5.00, prefer_local=5.00, prefer_streaming=0.00, prefer_healthier_provider=0.00]
DEBUG parika.core.planner.planner Selected provider=provider.ollama model=qwen3-coder:latest score=105.00 thinking_mode=auto reasoning_enabled=None selection_time_ms=0.295
```

Set `model_selection.log_decision = false` to silence just the
Planner-side selection logs (the Ollama-side per-request logs described
in section 8 are unaffected).

## 9.4 Routing Strategy (reducing routing latency)

The **routing model** is the model that receives your message first,
understands it, decides which tools/capabilities to use, and recommends
worker models for anything it delegates (see
[`Model_Selection_Framework.md`](../architecture/Model_Selection_Framework.md)
§13/§14). By default (`[routing_model] mode = "auto"`) it is selected
through the exact same scoring in section 9.1 as everything else - which
means a very simple message like "Hello" or "Thank you" can still score a
large, reasoning-heavy model (e.g. `qwen3-coder`) higher than a much
smaller, faster one, adding tens of seconds of latency just to route a
one-line request.

If you have a small, fast local model available (e.g. `qwen3:8b`), you
can pin it as the routing model to fix this, without changing how any
other (worker) model is selected:

```toml
[routing_model]
mode = "fixed"
fixed_model = "qwen3:8b"
fixed_thinking = false
```

- `fixed_model` accepts a bare model id, or `"provider_id/model_id"`
  (e.g. `"provider.ollama/qwen3:8b"`) if more than one provider could
  expose the same model id.
- `fixed_thinking = false` disables reasoning/"thinking" specifically
  for the routing model, regardless of `[model_selection.reasoning]` -
  this is usually where most of the latency win comes from.
- If `fixed_model` is not installed, is unavailable, or its provider is
  offline, Planner logs a warning and automatically falls back to
  `mode = "auto"` for that request rather than failing.
- Worker model selection (whatever model actually performs vision, OCR,
  coding, etc.) always continues to use the full scoring pipeline in
  section 9.1, completely unaffected by this setting.
- The legacy `[planner.routing]` section name is still accepted as a
  backward-compatible alias, but `[routing_model]` is the preferred
  name and always takes precedence when both are present.

------------------------------------------------------------------------

# 10. AI Context Engineering and Capability Discovery

Before the scoring described in section 9 runs, the AI Context
Engineering layer (`parika/interfaces/chat_capability.py`) builds the
model's runtime worldview: every currently enabled Capability is
discovered automatically from `CapabilityRegistry` and advertised to
the model, with no domain-specific keyword matching deciding which
tools are "relevant" to a given message. See
[`Request_Understanding.md`](../architecture/Request_Understanding.md)
for the complete design.

## 10.1 What Changed

PARIKA previously ran a Planner-internal Requirement Inference
framework that guessed `tool_calling`/`information_freshness`/
`capability_hints` from message text via regex, and a separate
Interfaces-layer keyword router (`tool_relevance.py`) that decided
which tool names to advertise per message. Both have been completely
removed. Now, every turn advertises the full roster of enabled
Capabilities (minus two fixed-scope memory-authorization gates - see
`Request_Understanding.md` §4.1), and the model itself decides,
through its own native tool-calling reasoning over each Capability's
description, whether a tool call is warranted:

```text
"Hello!"                                        -> full roster advertised; model calls nothing
"Summarize this document for me."               -> full roster advertised; model decides
"What is the current time in IST?"              -> full roster advertised; model calls get_current_datetime
"Latest AI news"                                -> full roster advertised; model calls web_search/news tools
"Who is the current Education Minister of India?" -> full roster advertised; model decides
```

`tool_calling="preferred"` is set structurally (whenever a non-empty
tool roster is offered, never from message content) as a
`Goal.metadata["execution_requirements"]` override, favoring
tool-calling-capable models in scoring without hard-excluding others
(unchanged Model Selection Framework behavior otherwise).

## 10.2 The Runtime Info Tool

A new built-in Tool/Module answers date/time questions deterministically,
the same way the Web Search Module already answers news/weather/office-
holder questions:

```text
$ parika
> What is the current time in IST?
The current time in IST (Indian Standard Time) is Wednesday, 29 July 2026,
11:54:31. This corresponds to a UTC offset of +05:30.
```

It reads the real system clock (stdlib `datetime`/`zoneinfo`, no network, no
AI call) and accepts an IANA timezone name or a common abbreviation
(`IST`, `UTC`, `EST`, ...).

## 10.3 Configuration

There is no configuration toggle left for this layer: capability
discovery is always automatic and always advertises every enabled
Capability (`[planning.requirement_inference]` and its `enabled` flag
have been removed along with the framework they configured).

## 10.4 Formerly a Known Limitation — Now Automatically Recovered

One locally installed model (`qwen3-coder:latest` in this environment) was
observed emitting a malformed pseudo tool-call as plain text specifically
when two or more tools were advertised at once, even though it correctly
used the standard tool-call format with only one tool advertised - a
model/template quirk in that specific Ollama build, confirmed via direct
`curl` reproduction, not a defect in PARIKA's tool-calling loop.

A subsequent backend hardening milestone added a **generic** fallback
parser that recovers this exact shape (and the Hermes/ChatML alternative)
regardless of which tool or capability is involved - see
[`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md).
You will see a `WARNING`-level log line when this happens:

```text
WARNING parika.providers.ollama.driver Recovered 1 tool call(s) from leaked
template markup in model=qwen3-coder:latest's response content instead of
the native tool_calls field: ['get_current_datetime']
```

The request still completes correctly and the tool still executes; the
warning is purely a diagnostic signal that a particular model's template
needed the fallback.

## 10.5 Tool Affordance Contract and Reasoning Policy

A later phase improved reasoning *quality* on top of Automatic
Capability Discovery: every model-callable Tool now advertises a
richer **Tool Affordance Contract** instead of a bare description and
parameters - purpose, when to use it, when to avoid it, what it
requires, and how to interpret its results and failures. For example,
`memory.remember`'s contract states it should only be used when the
user explicitly asks to remember/save/store something, and never for
information about PARIKA's own identity - guidance that used to be
hardcoded inside AI Context Engineering's system prompt and now lives
entirely on the Memory Tool itself (see `parika/tools/memory/
manifest.py`'s `MEMORY_TOOL_AFFORDANCES`).

The system prompt also now includes a general, capability-independent
**Reasoning Policy**: prefer Assistant Identity, then the current
conversation, then injected Memory, then injected Knowledge, then an
earlier Tool result, and only call a Tool when none of those already
answers the question. Every Tool's own contract is read within that
ordering - no capability id or tool name appears in the policy itself.
See [`Request_Understanding.md`](../architecture/Request_Understanding.md)
§4.4-§4.5 for the complete design.

------------------------------------------------------------------------

# 11. Provider Tool Calling Hardening

See [`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md)
for the complete design. In addition to the text-based fallback above:

- **Empty final responses are retried once, automatically.** Any model
  can occasionally produce a blank final answer (no tool call, no
  content) - a non-deterministic sampling outcome. PARIKA retries the
  exact same conversation once before giving up, logged at `WARNING`:

  ```text
  WARNING parika.providers.ollama.chat_loop Empty final response from
  model=...; retrying (1/1) with the same conversation.
  ```

- **Diagnosing tool-calling issues:** with `logging.level = "DEBUG"`,
  every request logs `advertised_tools=[...]` (exactly what was offered)
  and `Native tool calls received: ... count=N` (what Ollama's own field
  reported), so you can tell "the tool wasn't offered" from "the model
  chose not to call it" from "the model tried but needed the fallback" at
  a glance. See `Provider_Tool_Calling.md` §8 for a full example, and
  `docs/development/Provider_Tool_Calling_Guide.md` §4 for a diagnosis
  walkthrough.

------------------------------------------------------------------------

# 12. The Server Platform (REST/WebSocket API)

PARIKA also ships a long-running **Server Runtime**, exposing every
capability the CLI already provides over a versioned REST/WebSocket
API — the same execution pipeline (`Router → Planner/Brain` or
`Router → <Core manager>`), never a parallel one. See
[`Core_Component_Responsibilities.md`](../architecture/Core_Component_Responsibilities.md)
for the frozen Core this wraps unchanged, and
`docs/api/PARIKA_API_Reference.html` for the complete, generated
endpoint reference (Authentication, Requests, Responses, Streaming,
Errors, Versioning — kept separate from this operational guide).

## 12.1 Installing the `server` extra

```bash
pip install -e ".[server]"
```

Installs FastAPI, Uvicorn, Pydantic, `websockets`, and PyJWT. The
base `parika`/`python -m parika` CLI install never requires this
extra.

## 12.2 Running the server

```bash
python -m parika.server
# or, after installation:
parika-server
```

```text
$ python -m parika.server
INFO:     Uvicorn running on http://127.0.0.1:2026 (Press CTRL+C to quit)
```

No installer, system service, packaging, or Docker image is required
or provided — this is a development-mode entry point. Stopping the
process stops PARIKA; restarting it starts a fresh `ParikaRuntime`
(manual restart is expected during development). `--host`, `--port`,
`--reload`, and `--log-level` override `[api].host`/`[api].port`:

```bash
python -m parika.server --port 9000 --reload
```

**LAN access.** `[api].host` defaults to `"127.0.0.1"` (loopback-only)
and is read straight from configuration — never hardcoded — so the
default security posture never changes silently. To make the API (and
therefore a LAN-hosted Web Client, e.g. served by Apache from another
machine) reachable from other devices on the network, explicitly set
`[api].host = "0.0.0.0"` (typically in `config/installation.toml`,
which is machine-specific) or pass `--host 0.0.0.0`:

```bash
python -m parika.server --host 0.0.0.0
```

Before doing this, also set `[api.auth].mode = "api_key"` (section
12.5) — `mode = "none"` must never be paired with a non-loopback
`host` — and configure `[api.cors].allow_lan_origin_regex` (section
12.6) so the LAN Web Client's origin is actually allowed. The machine
firewall still applies: setting `host = "0.0.0.0"` only makes PARIKA
*listen* on every interface, it does not itself open any firewall
port.

## 12.3 Exercising the API

Every route is versioned under `/api/v1`, mirroring the CLI's own
slash commands one-for-one wherever an equivalent exists:

```bash
curl http://127.0.0.1:2026/api/v1/health
curl http://127.0.0.1:2026/api/v1/status
curl http://127.0.0.1:2026/api/v1/tools
curl -X POST http://127.0.0.1:2026/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello"}'
```

Interactive documentation (Swagger UI/ReDoc, auto-generated by
FastAPI from the same route/schema definitions) is served at `/docs`
and `/redoc` while the server is running.

**Streaming chat** uses a WebSocket rather than REST, with a
terminal `"type": "done"` message mirroring Ollama's own `"done":
true` convention:

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect(
        "ws://127.0.0.1:2026/api/v1/ws/chat/my-session"
    ) as ws:
        await ws.send(json.dumps({"text": "Hello"}))
        while True:
            message = json.loads(await ws.recv())
            print(message)
            if message["type"] == "done":
                break

asyncio.run(main())
```

**The generic capability endpoint** (`POST
/api/v1/capabilities/{capability_id}/execute`) reaches any registered
capability that does not (yet) have its own dedicated endpoint — it
is a compatibility fallback, never the preferred way to call a
capability that already has a proper domain-specific endpoint (e.g.
prefer `/api/v1/tools`/`/api/v1/modules`/`/api/v1/chat` over the
generic endpoint whenever one exists).

### Runtime/system telemetry (`GET /api/v1/status`)

`GET /api/v1/status` is the single, authoritative snapshot the PARIKA
Web Client (and any other API consumer) should use to display system
and runtime information — the browser/client never inspects the host
OS itself. Alongside the existing `lifecycle_state`/`execution_state`/
`interaction_state`/`overall_health`/module-capability-tool-provider
counts (unchanged, for backward compatibility), the response carries
these additional telemetry groups, all sourced from
`ResourceManager.get_resource_snapshot()` (see
docs/architecture/Core_Component_Responsibilities.md section 8):

| Group | Contents |
|---|---|
| `system` | `platform`, `operating_system`, `kernel_release`, `architecture`, `hostname` (redacted, see below), `boot_time`, `uptime_seconds`, `uptime_human`. |
| `cpu` | `usage_percent`, `logical_core_count`, `physical_core_count`, `load_average_1m/5m/15m` (Unix only), `current_frequency_mhz`. |
| `memory` | Host RAM: `total_bytes`/`available_bytes`/`used_bytes`/`free_bytes`, `usage_percent`, `swap_*_bytes`, `swap_usage_percent`. Distinct from `parika.memory_count` below (PARIKA's own long-term Memory subsystem, not host RAM). |
| `gpu` | `detected`, `available`, `devices: []` — one entry per detected NVIDIA GPU (`utilization_percent`, `memory_*_bytes`, `memory_usage_percent`, `temperature_celsius`, `power_usage_watts`, `power_limit_watts`). Always `{"detected": false, "available": false, "devices": []}` on hosts with no NVIDIA GPU, no driver, or the optional `gpu` extra not installed — this never fails the request. No other GPU vendor is implemented. |
| `temperature` | Non-GPU thermal sensors (CPU/package and whatever else the host platform's `psutil.sensors_temperatures()` reports — Linux only; `available: false` elsewhere). GPU temperature is reported per-device on `gpu.devices[].temperature_celsius` instead. |
| `storage` | The PARIKA workspace filesystem only (the same canonical project-root path `ResourceManager` already used for `disk`/`filesystem` telemetry) — never every mounted filesystem on the host. `path`, `total_bytes`, `used_bytes`, `free_bytes`, `usage_percent`. |
| `network` | Aggregate `bytes_sent`/`bytes_received`, `interface_count`/`active_interface_count`, and (when `resources.network_interfaces_enabled`) a per-interface `interfaces: []` breakdown. Never performs bandwidth/speed testing. |
| `parika` | PARIKA-runtime counts not already flat fields on this response: `version`, `available_providers`, `total_models`, `memory_count`/`memory_storage_bytes` (long-term Memory), `knowledge_engines`/`knowledge_sources`. |
| `timestamp` | When this specific snapshot was captured (ISO 8601, UTC). |

Every field the current host/build cannot determine is `null`
("unavailable"), never a fabricated zero or empty string — a Web
Client must render these as "N/A" (or equivalent), exactly like the
`/status` CLI command already does. Percentages are always computed
server-side (bounded `0`-`100`, rounded to two decimal places where
PARIKA computes them itself); a client should never need to divide
raw byte counts itself.

**Session/Planner diagnostics are CLI-only.** The `/status` slash
command additionally shows per-turn diagnostics (last selected
provider/model, Planner context tokens, memory/knowledge hits) sourced
from the active `InterfaceSession`. `GET /api/v1/status` has no
session context (`StatusRequest` takes none), so these are not part
of the REST response — a documented limitation, not an oversight.

**Hostname redaction.** `system.hostname`/`network.hostname` are
`null` unless an operator explicitly sets `api.expose_hostname = true`
in configuration (default `false`), since — unlike the CLI, already
running on the user's own machine — this REST response may be
reachable from other devices on a LAN or the Internet.

**Recommended Web Client refresh behavior.** PARIKA does not push
telemetry over the WebSocket today (see section 12.7's "Execution
progress events" for what *is* streamed); `ResourceManager` remains
deliberately on-demand, never a continuous background poller (see
docs/architecture/Core_Component_Responsibilities.md section 8), so a
Web Client should poll `GET /api/v1/status` on its own schedule. The
suggested interval is `resources.recommended_client_poll_interval_seconds`
in `config/defaults.toml` (`5.0` seconds by default) — poll no more
frequently than this without a specific reason, to avoid needlessly
spending CPU on `psutil`/NVML reads that nothing is currently
displaying.

### Voice API (`/api/v1/voice/`)

The server-side Voice capability (`parika.modules.voice`, backed by
`parika.providers.local_speech`'s local `faster-whisper`/Piper
engines) is available to any client through six endpoints, all
following this document's own conventions (versioned, authenticated,
the same centralized error envelope as every other route). Install
the optional `voice` extra (`pip install -e .[voice]`) and configure
`[providers.local_speech]` in `config/defaults.toml` (model
size/device/language for STT, and — importantly — `tts_model_path`/
`tts_hindi_model_path` each pointing at an installed Piper `.onnx`
voice model, which does not auto-download) before either direction
becomes available; with neither installed, `/voice/transcribe`/
`/voice/respond`/`/voice/speak` simply report an error rather than
PARIKA failing to start.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/voice/transcribe` | `audio -> text`. Pure speech-to-text; never enters the text pipeline. |
| `POST /api/v1/voice/respond` | `audio -> speech_to_text -> the same non-streaming pipeline POST /api/v1/chat uses -> canonical text response`. Never synthesizes speech for the reply — see below. |
| `POST /api/v1/voice/speak` | `text -> audio`. Independent of chat/respond; never generates the text itself. Accepts a caller-supplied `operation_id` for cancellation. |
| `POST /api/v1/voice/speak/{operation_id}/stop` | Cancels an in-progress `speak` operation. Never affects any PARIKA request or its already-produced text response. |
| `GET /api/v1/voice/settings` | Reads the current Voice language preference (input/output) plus an English/Hindi voice availability summary. |
| `PUT /api/v1/voice/settings` | Updates the current Voice language preference (`input_language`/`output_language`); either field may be omitted to leave it unchanged. |

```bash
curl -X POST http://127.0.0.1:2026/api/v1/voice/respond \
  -H "Content-Type: application/json" \
  -d '{"audio_base64": "<base64 WAV/etc.>", "session_id": "my-session"}'

curl -X POST http://127.0.0.1:2026/api/v1/voice/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello there.", "operation_id": "speak-1"}'

curl -X POST http://127.0.0.1:2026/api/v1/voice/speak/speak-1/stop

curl http://127.0.0.1:2026/api/v1/voice/settings

curl -X PUT http://127.0.0.1:2026/api/v1/voice/settings \
  -H "Content-Type: application/json" \
  -d '{"input_language": "hi", "output_language": "hi"}'
```

**`voice.respond` deliberately never auto-speaks its own reply.**
PARIKA's canonical response is always text, produced first; whether
to also hear it is an independent, client-controlled decision made
*after* the text response has actually arrived (the client calls
`/voice/speak` separately, with whatever text/voice preference is
current at that moment). This is what makes every input/output
combination — voice-in/text-out, voice-in/voice-out, text-in/text-out,
text-in/voice-out — and every "user changed their mind about voice
output while PARIKA was still processing" scenario correct without any
special-case logic; see ADR 0002
(`docs/architecture/adr/0002-voice-capability.md`) for the full
rationale.

**Long responses are spoken in chunks, and "Stop Speaking" is real,
not cosmetic.** `POST /voice/speak` splits its input text into small,
bounded pieces (`[voice].tts_chunk_max_characters`, default 280) and
synthesizes them one at a time; a concurrent
`POST /voice/speak/{operation_id}/stop` request (using the same
`operation_id`) stops synthesis between chunks and still returns
whatever audio was already produced (`"cancelled": true`) — it never
cancels, fails, or otherwise touches the PARIKA request that produced
the text being spoken.

#### English/Hindi language support

PARIKA Voice supports exactly two spoken languages, end to end:
English (`"en"`) and Hindi (`"hi"`); see
`parika/modules/voice/language.py` and ADR 0002's Decisions 7-10.

- **Input language** (`voice/transcribe`'s and `voice/respond`'s
  `language` field): `"auto"` (default — faster-whisper detects
  English or Hindi from the audio itself, never a Unicode-script
  heuristic and never the chat model guessing), `"en"`, or `"hi"`.
  The response reports `requested_input_language`,
  `detected_input_language`, and `language_source`
  (`"explicit"`/`"auto"`/`"unsupported"`).
- **Output language** (`voice/speak`'s `language` field): `"en"` or
  `"hi"`, explicitly, for that one call. Omit it to use the *current*
  output-language preference instead (`GET /voice/settings`'s
  `output_language`, one of `"en"`/`"hi"`/`"follow_input"`).
  `"follow_input"` speaks whatever language was most recently
  detected/used on the input side — set it via `PUT /voice/settings`.
- **Selecting a language explicitly:** `PUT /voice/settings` with
  `{"input_language": "hi", "output_language": "hi"}` (Hindi mode) or
  `{"input_language": "en", "output_language": "en"}` (English mode).
  Explicit selection is per input/output side independently — a
  caller is never forced to keep both in lock-step.
- **Auto mode:** the default, `{"input_language": "auto",
  "output_language": "follow_input"}` — speech is detected
  automatically and spoken back in whatever language was detected.
- **Changing language mid-processing never cancels an in-flight
  request.** `PUT /voice/settings` only ever affects the *next*
  `transcribe`/`speak` call, exactly like deciding whether to call
  `/voice/speak` at all already worked before this addition (see
  "`voice.respond` deliberately never auto-speaks" above) — this is
  the same principle, extended to *which* language.
- **Mixed Hindi/English ("Hinglish") speech:** faster-whisper returns
  one single language classification per utterance; PARIKA passes
  that through as-is rather than attempting to split or reclassify
  it. Expect the dominant language of the utterance to win; there is
  no dedicated Hinglish category.

#### Configuring Indian female voices

- **Hindi:** download `hi_IN-priyamvada-medium.onnx`/`.onnx.json` from
  `https://huggingface.co/rhasspy/piper-voices` (a real, confirmed-
  female Hindi/India Piper voice) and set
  `[providers.local_speech].tts_hindi_model_path` (and, if the `.json`
  config is not a sibling file, `tts_hindi_config_path`) to their
  paths.
- **English:** Piper's official voice catalog has **no** dedicated
  Indian-English (`en_IN`) locale at all — only `en_US`/`en_GB`. There
  is therefore no real Indian-accented English Piper voice to
  configure today. The default English voice
  (`[providers.local_speech].tts_voice`/`tts_model_path`) is
  `en_US-amy-medium`, a real, confirmed-**female** voice — the closest
  available substitute, explicitly **not** Indian-accented. This is a
  documented limitation of Piper's current voice catalog, not a
  PARIKA implementation gap; revisit if/when Piper publishes a
  dedicated Indian-English voice.
- Both `tts_model_path` and `tts_hindi_model_path` are independent:
  configuring only one still makes that language's text-to-speech
  available (the other language then falls back to whichever voice
  *is* configured, per `PiperTtsEngine`'s own graceful-fallback
  behavior, rather than failing).

#### Troubleshooting

- **"Text-to-speech via Piper requires ... to be installed"** — the
  `voice` extra is not installed (`pip install -e .[voice]`).
- **"... requires [providers.local_speech].tts_model_path to be set
  to an installed Piper voice model (.onnx) file"** — neither voice
  slot has a valid, existing `.onnx` path configured yet.
- **"Configured faster-whisper model '...' is English-only"** — an
  `stt_model_size` ending in `.en` (e.g. `small.en`) was combined with
  an explicit or auto-resolved Hindi request; use a multilingual
  checkpoint (e.g. plain `small`, `medium`, `large-v3`) instead.
- **CPU fallback:** `stt_device`/`tts_device = "auto"` (the default)
  tries GPU first, then transparently falls back to CPU if no GPU/
  driver is available — no configuration change needed for a CPU-only
  machine.
- **Engine unavailable:** `GET /api/v1/voice/settings`'s
  `stt_available`/`tts_available` fields, and `/status`'s `Voice:`
  section in the CLI, report current availability without needing to
  attempt a real transcribe/speak call first.

### Media API (`/api/v1/media/`, `WS /api/v1/ws/media/{client_id}`)

**PARIKA server = media intelligence + resolution + command/state
protocol. PARIKA server ≠ media player.** The server-side Media
Capability (`parika.modules.media`, backed by `parika.tools.media`)
resolves and controls playback intent; a separate, future **Web
Client** performs actual audio/video decoding and rendering. See
ADR 0004 (`docs/architecture/adr/0004-media-capability.md`) for the
full architectural decision this section documents the contract for.

This section is written for two audiences: PARIKA's own natural-
language behavior ("Play Imagine Dragons Believer" → a `media.play`
Tool call), and the future, separate Web Client developer who
implements the other half of this contract in their own codebase.

#### Media Capability

| Capability / Tool | Purpose |
|---|---|
| `media.play` (`tool.media_play`) | Resolve a query (search text, local path, YouTube URL, or direct media URL) and dispatch `media.play` to the Web Client. |
| `media.pause` / `media.resume` / `media.stop` | Pause/resume/stop playback in the Web Client. |
| `media.skip` / `media.previous` | Move to the next/previous queued item. |
| `media.seek` | Seek to `position_seconds` (a non-negative number). |
| `media.set_volume` | Set `volume_percent` (0-100). |
| `media.mute` / `media.unmute` | Mute/unmute audio output. |
| `media.show` / `media.hide` | Show/hide the video/player surface. |
| `media.get_state` | Read PARIKA's last known `MediaState` - never dispatches a command. |

Every command Tool returns one of three result shapes - never a claim
that playback actually happened:

- `{"status": "dispatched", "command": "media.play", "source": {...}}`
  - the command was enqueued to at least one connected Web Client.
  Actual playback is still pending confirmation - see "Acknowledgement
  and actual playback result" below.
- `{"status": "unavailable", "message": "..."}` - **no compatible Web
  Client is currently connected.** PARIKA never pretends playback
  started when this happens; the model is instructed (via each Tool's
  affordance contract) to tell the user playback control is not
  currently available.
- `{"status": "not_found" | "unsupported" | "invalid", "message": "..."}`
  - `media.play` could not resolve a source (`not_found`), the query
  was a webpage URL rather than playable media (`unsupported`), or
  `media.seek`/`media.set_volume` received an invalid value
  (`invalid`).

`GET /api/v1/media/state` mirrors `media.get_state` as a plain REST
read (no auth-bearing Tool call needed), so a Web Client can render
PARIKA's last known state on load/reconnect:

```bash
curl http://127.0.0.1:2026/api/v1/media/state
```

```json
{
  "status": "idle",
  "source": null,
  "position": null,
  "volume": 1.0,
  "muted": false,
  "playback_rate": 1.0,
  "visible": false,
  "client_connected": false,
  "error_message": null,
  "updated_at": "2026-08-09T12:00:00+00:00"
}
```

`status` is one of `idle`/`loading`/`playing`/`paused`/`stopped`/
`buffering`/`ended`/`error`. **The Web Client is the sole authority
for actual playback**; `position` and `status` are only ever as fresh
as the most recent Web-Client-reported event - PARIKA never advances
`status` to `playing` on its own (dispatching `media.play` only ever
moves the locally-held status to `loading`). `client_connected=false`
means no Web Client is connected over the Media WebSocket at all
right now, regardless of what `status` last was.

#### Media source types

A `MediaSource` always has a `type`, and only the fields relevant to
that type are populated:

```json
// type = "youtube": PARIKA never extracts/downloads a raw stream -
// the Web Client must use an official YouTube-supported browser
// integration (e.g. the IFrame Player API).
{"type": "youtube", "url": "https://www.youtube.com/watch?v=...", "media_id": "...", "title": "...", "artist": null, "album": null, "duration": null, "mime_type": null}

// type = "local": a path on the PARIKA *server's* filesystem - see
// "Local files" below for why a Web Client cannot simply put this in
// an HTMLMediaElement `src`.
{"type": "local", "path": "/home/pushpesh/Music/test.mp3", "title": "test.mp3", "url": null, "media_id": null, "artist": null, "album": null, "duration": null, "mime_type": "audio/mpeg"}

// type = "direct_url": a URL that already points at a playable media
// file (recognized by extension), never an arbitrary webpage.
{"type": "direct_url", "url": "https://example.com/song.mp3", "mime_type": "audio/mpeg", "title": null, "path": null, "media_id": null, "artist": null, "album": null, "duration": null}

// type = "stream": a network stream manifest (e.g. HLS `.m3u8`).
{"type": "stream", "url": "https://example.com/live/index.m3u8", "title": null, "path": null, "media_id": null, "artist": null, "album": null, "duration": null, "mime_type": null}
```

**Unknown/future source types.** A future PARIKA version may add a
new `type` (documented as a breaking wire-format change, following
section 12.9's API stability rules identically for WebSocket
messages). A Web Client that receives a `type` it does not recognize
must fail clearly (e.g. report an unsupported-source error) rather
than guess a playback strategy for it.

#### Media resolution

"Play Imagine Dragons Believer" resolves in this order (see
`parika.tools.media.resolution.MediaResolver`):

1. **Local filesystem path** - an absolute/home/relative-directory-
   shaped query, or one already carrying a recognized media
   extension. Validated against `[media].allowed_local_roots` (see
   "Local files" below).
2. **URL** - classified as a recognized YouTube link
   (`youtube.com`/`youtu.be`, `watch`/`shorts`/`embed`/`live`), a
   direct media file (by extension: `.mp3`/`.wav`/`.mp4`/`.webm`/...),
   or a stream manifest (`.m3u8`/`.mpd`). Any other URL is rejected
   as `"status": "unsupported"` - **PARIKA never assumes an arbitrary
   webpage is playable media.**
3. **Free text** - falls back to the existing `web.search` Capability
   (`"<query> site:youtube.com"`), through the same nested-Goal-via-
   `Brain.handle()` pattern the Voice Capability already uses to
   reuse `filesystem.read`/`filesystem.write` - never a hardcoded
   YouTube API client, never `yt-dlp`. The first search result that
   is itself a recognized YouTube link becomes the resolved
   `MediaSource`. Disable this fallback with
   `[media].youtube_search_enabled = false` (local-path/direct-URL/
   YouTube-URL resolution remain available either way).

"play any south indian movies from youtube" is exactly this same
free-text path - PARIKA does not have (and does not add) a separate
"browse/discover" capability; it is still one resolved source per
`media.play` call.

#### Local files

**"Play the song in /home/pushpesh/Music/test.mp3" does not mean the
browser can access that path.** A server-side filesystem path is
*never* directly usable as an `HTMLMediaElement` `src` from a remote
(or even same-machine, different-process) browser. PARIKA:

- Represents this as `{"type": "local", "path": "...", ...}` and
  requires the path to resolve under an explicitly configured
  `[media].allowed_local_roots` entry (empty by default - local
  media resolution is **disabled** until an operator opts in; see
  `parika/tools/media/security.py`'s module docstring for why this is
  narrower than the Filesystem Tool's own default-open reads).
- **Never implements a filesystem-serving endpoint.** There is no
  `GET /api/v1/media/local?path=...` or equivalent, and none should be
  added merely to make local playback "just work" - see ADR 0004's
  "Alternatives Considered".

Actually delivering local media bytes to the browser is a **Web
Client integration responsibility** - e.g. the browser's File System
Access/File API (the user picks the file client-side, matching by
name/path against what PARIKA resolved), or a separately designed,
narrowly-scoped, authenticated local-media bridge if a future task
genuinely requires server-initiated delivery. Neither is implemented
here.

#### YouTube integration boundary

PARIKA never downloads, decodes, or extracts a raw stream URL for a
YouTube source - only `url`/`media_id`/descriptive metadata are ever
provided. The Web Client is expected to embed an official YouTube-
supported browser player (e.g. the IFrame Player API, as
`videojs-youtube` wraps) using `media_id`. This is a hard boundary,
not a temporary limitation.

#### Direct URL limitations

A direct media URL (`https://example.com/song.mp3`) is not guaranteed
to actually play in a browser even once dispatched - CORS policy,
MIME type mismatches, authentication requirements, DRM, hotlink
protection, and provider-specific restrictions are all real,
possible failure modes entirely outside PARIKA's control. PARIKA
never claims `"status": "dispatched"` means the media will play -
only that the Web Client received the command; see "Acknowledgement
and actual playback result" below for how a genuine failure is
reported back.

#### Bidirectional contract

**Server → Web Client** (commands, dispatched by
`MediaToolDriver`/`MediaConnectionRegistry` over the Media WebSocket):

```json
{"type": "media.play", "payload": {"source": {"type": "youtube", "url": "...", "media_id": "..."}}}
{"type": "media.pause"}
{"type": "media.resume"}
{"type": "media.stop"}
{"type": "media.skip"}
{"type": "media.previous"}
{"type": "media.mute"}
{"type": "media.unmute"}
{"type": "media.show"}
{"type": "media.hide"}
{"type": "media.seek", "payload": {"position_seconds": 90.0}}
{"type": "media.set_volume", "payload": {"volume_percent": 50.0}}
```

**Web Client → Server** (events, applied to PARIKA's `MediaState`):

```json
{"type": "media.ready"}
{"type": "media.state_changed", "payload": {"state": {"status": "playing", "position": 12.4, "volume": 0.8, "muted": false, "source": {...}}}}
{"type": "media.position_changed", "payload": {"position": 12.4}}
{"type": "media.play_started"}
{"type": "media.play_paused"}
{"type": "media.play_stopped"}
{"type": "media.play_ended"}
{"type": "media.buffering"}
{"type": "media.error", "payload": {"message": "Autoplay was blocked by the browser."}}
{"type": "media.source_changed", "payload": {"source": {...}}}
```

Every message uses the same minimal `{"type": ..., "payload": ...}`
envelope already established by the Chat WebSocket's `ChatWs*` schemas
(`parika/api/schemas/chat.py`) - a `type` string discriminator plus
domain fields, rather than a second, competing envelope with its own
`message_id`/`correlation_id`/`version` (PARIKA has no existing
generic message envelope with those fields to reuse - see ADR 0004's
Context - and this Capability does not need per-message correlation
IDs today: every command is fire-and-forget, and every event is
applied directly to `MediaState` rather than matched back to a
specific prior command). **Command IDs/correlation IDs**: not part of
this increment's contract; a future increment could add an optional
`command_id` to each server→client command and echo it back in the
corresponding Web Client event, without breaking any existing message
shape (an unrecognized/absent field is always ignored, never
required).

#### Web Client readiness and connecting

`WS /api/v1/ws/media/{client_id}` uses the exact same authentication
mechanics as the Chat WebSocket (`Authorization: Bearer ...`,
`X-API-Key`, or `?token=` - see section 12.5). `client_id` is a
caller-chosen identifier for this connection (e.g. a browser tab/
session id) - it is not a chat session id and has no relationship to
one.

```python
import asyncio
import websockets

async def main():
    async with websockets.connect(
        "ws://127.0.0.1:2026/api/v1/ws/media/my-web-client"
    ) as ws:
        # Send this only once this client can actually accept a
        # command (e.g. once its own player is initialized) - PARIKA
        # will not dispatch anything to this connection before it does.
        await ws.send('{"type": "media.ready"}')

        async for raw in ws:
            print("command from PARIKA:", raw)
            # ... actually play/pause/seek/etc. using the browser's
            # own media APIs, then report back, e.g.:
            # await ws.send('{"type": "media.play_started"}')

asyncio.run(main())
```

- **`media.ready`** announces that this connection is actually ready
  to receive media commands. **Connected and ready are two distinct
  things:** a WebSocket connecting only registers the connection
  (`MediaConnectionRegistry.register()`) and marks
  `MediaState.client_connected = true`; that connection is not
  dispatchable (`MediaConnectionRegistry.dispatch()` skips it) until
  it explicitly sends `{"type": "media.ready"}`
  (`MediaConnectionRegistry.mark_ready()`). `media.ready` itself does
  not change `MediaState` - readiness is tracked per-connection, in
  the connection registry, not as a `MediaState` field. A Web Client
  should send it as soon as its own player is actually able to accept
  a command, not merely as soon as the socket opens.
- **Connecting at all** already marks `MediaState.client_connected =
  true`; disconnecting (cleanly or not) marks it `false` again once
  the server observes the closed connection, and also discards that
  connection's readiness - a client that reconnects (even with the
  same `client_id`) starts not-ready again and must send
  `media.ready` again.
- **Multiple simultaneous connections** are supported: every *ready*
  connected Web Client receives every dispatched command. PARIKA does
  not yet arbitrate "who is the authoritative player" when more than
  one Web Client is ready - see ADR 0004's "Intentionally Deferred".

#### Disconnected / not-ready behavior

- **No Web Client connected at all, or connected but not yet
  ready:** every command Tool (and the underlying WebSocket dispatch)
  reports `{"status": "unavailable", ...}` immediately - `media.play`
  never pretends "Believer" started playing just because PARIKA
  successfully resolved a YouTube video for it, and a connection that
  has opened but not yet sent `media.ready` is treated exactly like
  no connection at all for dispatch purposes.
- **Commands before `media.ready`:** PARIKA *requires* `media.ready`
  before dispatching a command to a connection - see above. A real Web
  Client should send `media.ready` only once it can actually accept a
  command (e.g. once its own player is initialized), since PARIKA will
  otherwise correctly treat it as not yet available rather than
  queueing commands on its behalf.
- **Duplicate commands:** each `media.*` Tool call is independent and
  idempotent from PARIKA's perspective - two `media.pause` calls in a
  row simply dispatch `media.pause` twice; the Web Client is
  responsible for treating a second pause of an already-paused player
  as a no-op, exactly as it would for a duplicate UI click.

#### Acknowledgement and actual playback result

**Dispatching `media.play` is not proof of playback**, and PARIKA
never claims otherwise. The real lifecycle is:

```
command accepted (Tool call returns "dispatched")
        -> Web Client receives the command over the WebSocket
        -> Web Client attempts playback using its own player
        -> Web Client reports loading/playing/error back
              (media.play_started / media.buffering / media.error /
               media.state_changed)
        -> PARIKA updates MediaState (MediaStateStore.apply_client_event)
```

YouTube may reject playback, the browser's autoplay policy may block
it, a direct media URL may 404/CORS-fail, the source may simply be
unavailable, or the Web Client may not be ready at all - none of
these are PARIKA failures; they are reported back exactly like a
successful `media.play_started` is, via `media.error`/
`media.state_changed`, and `GET /api/v1/media/state`'s
`status`/`error_message` reflect whichever actually happened.

#### UI-originated actions (Web Client controls)

A user clicking **Pause** inside the Web Client is not a second,
hidden state PARIKA never learns about - it is expected to flow back
exactly like a voice/typed command's *result* would:

```
User clicks Pause in the Web Client
        -> Web Client pauses its own player
        -> Web Client sends {"type": "media.play_paused"} (or a
           {"type": "media.state_changed", ...} with status="paused")
        -> PARIKA applies it to MediaState
```

The Web Client must operate one logical media engine/state for both
origins (PARIKA-issued commands and its own UI controls) - never two
separate, unsynchronized states - so that a subsequent
`media.get_state`/`GET /api/v1/media/state` read (from either a voice
command or the same UI) is always consistent with what the user
actually sees.

#### Concurrency / non-blocking behavior

Issuing `media.play` never blocks the rest of PARIKA's request
processing. `MediaConnectionRegistry.dispatch()` only schedules
delivery (`loop.call_soon_threadsafe(...)`) and returns immediately -
it never waits for the Web Client to receive, act on, or confirm a
command. Immediately after "Play Imagine Dragons Believer", the same
conversation can ask "What is the weather?" or "Create a reminder"
without waiting on media at all; see
`tests/tools/media/test_driver.py::TestNonBlockingPlay` for the
deterministic proof (an unrelated Tool call executes through the same
`ToolManager` immediately after a `media.play` dispatch, even while
the target Web Client connection's own event loop is deliberately
kept busy).

#### Versioning / forward compatibility

This Capability follows section 12.9's existing API stability rules
identically for WebSocket messages: new optional fields may be added
to any command/event/state payload without notice; existing fields
are never repurposed or removed; a new `MediaSourceType` member or a
new WebSocket message `type` is documented here as an additive,
backward-compatible change, and a Web Client encountering one it does
not recognize should fail clearly for that one message/source rather
than guess. There is no separate media-specific versioning scheme -
PARIKA does not introduce a second version number alongside this
project's existing API version.

#### End-to-end examples

**"Play Imagine Dragons Believer" (free text, resolved via
`web.search`):**

```
User: "Play Imagine Dragons Believer"
  -> media.play(query="Imagine Dragons Believer")
  -> MediaResolver resolves it to a youtube MediaSource via web.search
  -> {"type": "media.play", "payload": {"source": {"type": "youtube", ...}}}
     dispatched to the connected Web Client
  -> Web Client loads the YouTube IFrame player, starts playback,
     reports media.play_started
```

**"Play this YouTube video" (a YouTube URL already given):**

```
User: "Play this YouTube video https://www.youtube.com/watch?v=..."
  -> media.play(query="https://www.youtube.com/watch?v=...")
  -> Recognized directly as a youtube MediaSource (no search needed)
  -> dispatched identically to the free-text case above
```

**"Play the song in /home/pushpesh/Music/test.mp3" (local file):**

```
User: "Play the song in /home/pushpesh/Music/test.mp3"
  -> media.play(query="/home/pushpesh/Music/test.mp3")
  -> Validated against [media].allowed_local_roots; resolved to a
     local MediaSource
  -> Web Client uses whatever approved local-media mechanism it
     implements (see "Local files" above) - not a PARIKA-served byte
     stream
```

**"Pause" / "Resume" / "Skip" / "Set volume to 50%" / "Show the
video" / "Stop playing":**

```
User: "Pause"       -> media.pause -> {"type": "media.pause"} dispatched
User: "Resume"       -> media.resume -> {"type": "media.resume"} dispatched
User: "Skip"         -> media.skip -> {"type": "media.skip"} dispatched
User: "Set volume to 50%" -> media.set_volume(volume_percent=50)
                      -> {"type": "media.set_volume", "payload": {"volume_percent": 50.0}}
User: "Show the video" -> media.show -> {"type": "media.show"} dispatched
User: "Stop playing"  -> media.stop -> {"type": "media.stop"} dispatched
```

**Web UI clicks Pause** - see "UI-originated actions" above; the Web
Client pauses its own player and reports `media.play_paused` (or
`media.state_changed`), which PARIKA applies to `MediaState` exactly
like any other Web-Client-reported event.

**"Play Believer" while it plays, then "What is the weather?"** - see
"Concurrency / non-blocking behavior" above: the weather request is
handled completely independently; media continues playing in the Web
Client the entire time.

#### Web Client Media Integration Contract

This is the section a **future, separate Web Client** developer
implements against. Nothing described here exists in this
repository - it is guidance only, and no frontend/JavaScript/HTML file
was created by this change.

The Web Client should have one logical media engine/state, shared by
both PARIKA-issued commands and its own UI controls (see "UI-
originated actions" above):

```
MediaController
    |
    +-- MediaEngine
    |      |
    |      +-- LocalMediaAdapter     (browser File API / user-selected file)
    |      +-- YouTubeMediaAdapter   (official YouTube IFrame Player API)
    |      +-- DirectUrlMediaAdapter (HTMLMediaElement, subject to CORS/MIME/DRM)
    |      +-- Future adapters       (new MediaSourceType members)
    |
    +-- MediaState                   (mirrors this document's MediaState shape)
    |
    +-- MediaControls                (UI: play/pause/skip/seek/volume/show/hide)
    |
    +-- Visualizer/Canvas            (optional; Web Audio API + AnalyserNode,
    |                                 e.g. inspired by wavesurfer.js - client-side only)
    |
    +-- PARIKA WebSocket/Event Adapter (WS /api/v1/ws/media/{client_id})
```

Implementation choices explicitly left to the Web Client (never
PARIKA server dependencies):

- Full video playback: evaluate **Video.js** (a mature adapter-per-
  source architecture is exactly what informed `MediaSourceType`
  above).
- YouTube embedding: evaluate **videojs-youtube**'s official-IFrame-
  API integration pattern.
- HLS/stream playback (`MediaSourceType.STREAM`): evaluate **hls.js**.
- Audio waveform visualization: evaluate **wavesurfer.js**.
- Media control UI: evaluate **Media Chrome**.

None of these are PARIKA server dependencies, and none may ever be
added to `pyproject.toml` for this Capability - see ADR 0004.

## 12.4 Health, readiness, and liveness

Three small, always-unauthenticated operational endpoints exist
alongside the richer `/api/v1/status`:

| Path | Meaning |
|---|---|
| `GET /api/v1/health` | Basic reachability — answers the instant the HTTP server is up. |
| `GET /api/v1/live` | Process liveness — the event loop is responsive. |
| `GET /api/v1/ready` | Readiness — `200` only once `ParikaRuntime` has finished constructing; `503` during the brief startup window. |

## 12.5 Authentication

`[api.auth].mode` in `config/defaults.toml` selects the authentication
backend with no code change required to switch between them:

```toml
[api.auth]
mode = "none"          # "none" | "api_key" | "jwt"
api_keys = []            # hashed values, see below
jwt_secret = ""
jwt_expiry_seconds = 3600
```

| Mode | Deployment | Notes |
|---|---|---|
| `none` (default) | Local Development | Every request is authenticated unconditionally. Never use for a LAN/Internet-facing deployment. |
| `api_key` | LAN | Send `Authorization: Bearer <key>` or `X-API-Key: <key>`. Configured keys are hashed, never plaintext. |
| `jwt` | Internet | Send `Authorization: Bearer <token>`. `jwt_secret` must be set (sourced from an environment/runtime configuration layer, never committed to `defaults.toml`). |

Hash a plaintext API key for `[api.auth].api_keys` with:

```python
from parika.api.auth import configure_hashed_api_keys
print(configure_hashed_api_keys(["your-plaintext-key"])[0])
```

`/api/v1/health`, `/api/v1/live`, and `/api/v1/ready` are always
exempt from authentication.

## 12.6 CORS and rate limiting

```toml
[api.cors]
allow_origins = []
allow_origin_regex = "http://(127\\.0\\.0\\.1|localhost)(?::\\d+)?"
allow_lan_origin_regex = ""

[api.rate_limit]
enabled = false
requests_per_minute = 600000
```

`allow_origin_regex` (default: any `http://127.0.0.1`/`http://localhost`
origin, with or without a port) is always active. `allow_lan_origin_regex`
is an additional, explicitly configured pattern for a LAN Web Client —
e.g. Apache serving it from `http://192.168.1.100/parika-web/` sends
`Origin: http://192.168.1.100`:

```toml
# config/installation.toml (machine-specific — never defaults.toml)
[api.cors]
allow_lan_origin_regex = "http://192\\.168\\.1\\.100(?::\\d+)?"
```

Empty (the default) disables LAN origin matching entirely. When set,
it is combined with — never replaces — `allow_origin_regex`, so
localhost/127.0.0.1 access is unaffected. Configure the machine's
actual LAN IP explicitly; never a subnet wildcard, never
`allow_origins = ["*"]`, and never an HTTPS origin (the API is
plain HTTP only, matching `allow_origin_regex`'s existing `http://`-only
scheme). See section 12.2 for the matching `[api].host = "0.0.0.0"`
LAN binding change this pairs with.

`[api.rate_limit]` is currently configuration-only (not yet enforced
by a middleware); documented here for forward compatibility.

## 12.7 Relationship to the PARIKA Console

PARIKA has two permanently separate concepts (Phase 3.5b) -- this is
not a transitional state pending a future redesign:

- The **PARIKA Console** (`parika/console/`, formerly
  `parika/interfaces/cli/`), described in section 8, is PARIKA's
  native, in-process administration console. It constructs its own
  `ParikaRuntime` directly and calls `Brain.handle()` in-process,
  exactly as it always has. It is **not** an external client: it is
  not routed through `/api/v1`, is not subject to `[api.auth]`
  authentication or `[api.rate_limit]` rate limiting, and this will
  never change -- a previously proposed plan to redesign the Console
  into a pure API client ("Server Console") is cancelled. The Console
  remains PARIKA's primary administration/debugging/diagnostics
  interface.
- The Server Runtime and its `/api/v1` surface are for **external**
  clients only: Desktop, Web, Android, iOS, Voice, and a future CLI
  client (all out of scope until built). See section 12.9 for the
  stability rules that surface must uphold for those future clients.

Treat the Console and the API server as permanently separate entry
points into the same underlying Core, each constructing its own
`ParikaRuntime`.

### Execution progress events

Phase 3.5b adds live execution-progress reporting, reusing the
existing `EventBus`/`ProgressReporter` mechanism
(`parika/core/utilities/progress.py`) -- no new event system:

- `Brain.handle()` self-publishes one `brain.execution.*` tree per
  request (`brain.execution` root, `brain.planning` and
  `brain.execute_goal` children), via an optional `event_bus`
  constructor parameter.
- `MemoryManager.search()` and `KnowledgeManager.search()`
  self-report `memory.search.*`/`knowledge.search.*` as independent
  activities, using their own already-injected `EventBus`.
- `CapabilityExecutor`'s existing `capability.execution.started/
  completed/failed` events (already covering "Executing Capability")
  now carry an additive `task_id` field correlating them to the
  owning `TaskManager` `Task`.
- The Console renders all of the above live
  (`parika/console/progress_view.py`, `ConsoleProgressRenderer`),
  since it shares the same in-process, synchronous `EventBus` as
  every Core component -- see `[interfaces.cli].progress` in
  `config/defaults.toml`.
- `InterfaceSession.submit_text()` additionally captures every
  published `ProgressEvent` for the turn into
  `LastTurnDiagnostics.progress_trail`, for post-hoc diagnostics only
  (e.g. a later `/status` inspection); this never affects live
  delivery to any other subscriber.

**REST/WebSocket exposure of execution progress is deliberately
deferred, not implemented this phase.** The WebSocket chat handler
(`parika/api/ws/chat.py`) already buffers token fragments rather than
truly interleaving them with generation, because `handle_chat()` must
run synchronously on the connection's own event-loop task (a SQLite
`check_same_thread` constraint -- see that file's docstring). Shipping
execution-progress events over the same buffered mechanism would
deliver them only after the turn already completed, misrepresenting
them as live for no real benefit. Exposing them to REST/WebSocket
clients is tracked as a follow-up increment, alongside the existing
token-interleaving follow-up mentioned in `parika/api/ws/chat.py`.

## 12.8 Regenerating the API reference

```bash
python scripts/generate_api_docs.py
```

Rebuilds `docs/api/PARIKA_API_Reference.html` from the live
`parika.server.app.create_app()`'s OpenAPI schema (no running server
or Ollama instance required). Commit the regenerated file whenever
`parika/api/`'s routers or schemas change.

## 12.9 API Stability Rules

`/api/v1` is intended to become PARIKA's permanent public interface —
every future client (Desktop, Web, Android, iOS, future CLI, Voice)
must be able to use it without a backend redesign. Once an endpoint
ships, the following rules govern every change to it:

1. **Existing endpoints are never renamed.** A path, once published
   under `/api/v1`, keeps that exact path for `v1`'s entire lifetime.
2. **Existing request fields are never removed.**
3. **New fields must be backward compatible** — optional, with a
   sensible default, so an existing client that has never heard of
   the field continues to work unmodified.
4. **Breaking changes require a new API version** (`/api/v2`, mounted
   alongside `/api/v1`, never replacing it) — never a partial patch of
   `v1`'s routers.

These rules apply identically to REST fields and WebSocket message
`type` values. `parika/api/schemas/common.py`'s `ApiModel` base class
(`extra="ignore"` rather than `"forbid"`) enforces rule 3 at the
schema level: an unrecognized field on an incoming request is ignored,
never a validation error.
