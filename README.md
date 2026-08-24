
# PARIKA

**Personal Adaptive Responsive Intelligence Kernel Assistant**

PARIKA is a **local-first, modular, provider-independent AI orchestration platform** written in Python. It coordinates AI providers, deterministic tools, capabilities, and workflows through a stable Core. It is **not** a chatbot or an operating system.

> **Note**
> PARIKA is under active development. This README documents the current implementation. Planned or incomplete features are identified in **Known Limitations**.

---

## Table of Contents

1. What Is PARIKA?
2. Features
3. Architecture Overview
4. Intelligent Model Selection
5. Requirement Inference
6. Repository Structure
7. Prerequisites
8. Installation (Steps 1–6)
9. Run PARIKA
10. Run Tests
11. Examples
12. Project Configuration
13. Project Lifecycle
14. Development
15. Troubleshooting
16. Known Limitations
17. Contributing
18. License

---

## What Is PARIKA?

- Local-first
- Modular
- Extensible
- Provider-independent
- Capability-driven
- Tool-based
- Python 3.14+
- Supports local and cloud AI

See the documentation in `docs/architecture/` for the complete architecture.

---

## Features

- Local-first execution
- Capability-driven routing
- Provider independence
- Deterministic Tools
- Event-driven Core
- Policy-driven execution
- Modular architecture
- Automated tests
- Web Search reference implementation (multi-provider failover,
  relevance ranking, and result deduplication)
- Built-in Filesystem, Weather, Currency, News, and Expense Management
  Tools - all standard-library-only or keyless, no API keys required
  (see `docs/architecture/Tools_Expansion_Phase1_Plan.md` and
  `docs/architecture/adr/0003-expense-management.md`)
- The native PARIKA Console (streaming, Markdown, native tool calling,
  live execution-progress rendering)
- A production Ollama Provider (any installed Ollama-compatible model —
  qwen, llama, mistral, deepseek, glm, and more)
- Intelligent, configuration-driven model selection (no manual model
  picking, no hardcoded scores)
- Requirement-aware planning (tool necessity/freshness inferred from the
  request, not a fixed default)
- Hardened, framework-validated native Provider tool calling (generic
  fallback recovery for malformed model output, automatic recovery from
  blank final responses, provider reconnect)
- **System Interaction Foundation** — a Shell Tool
  (`shell.execute`/`background`/`processes`/`kill`, disabled by
  default), a workspace-based Filesystem Tool access model (any file
  may be read; writes/deletes/execution are confined to trusted
  workspaces, with an interactive escalation prompt otherwise), and a
  centralized Workspace Permission Manager every present and future
  Tool that touches a workspace shares (see "Workspace Permissions"
  below)
- **Developer Intelligence Platform** — semantic source-code
  understanding (parsing, symbol indexing, search, cross-reference/
  call-hierarchy analysis, rename/refactor planning, patch generation,
  documentation drafting, formatting/linting, complexity/duplicate/
  dead-code detection) via the Coding Tool (`coding.*`, 16 target
  languages — Python fully via stdlib `ast`, others via an optional
  Tree-sitter extra with automatic, graceful fallback); Workspace/
  Repository Understanding and Project Indexing via the Repository
  Intelligence Module (repository/project discovery, README
  understanding, read-only Git metadata, automatic framework/build-
  system/test-framework detection); and the Coding Agent
  (`coding.execute_task`) — a pure orchestrator over Planner/Brain/the
  Coding Tool/the Filesystem Tool/the Shell Tool that decomposes a
  coding request into a validated, capability-targeting plan before
  executing it, with an internal, pluggable multi-agent registry for
  future specialized agents (see `docs/development/Tool_Guide.md` §24,
  `docs/development/Module_Guide.md` §18, and
  `docs/development/Capability_Guide.md` §15)
- **Generic, ecosystem-wide progress reporting**
  (`parika.core.utilities.progress`) — any Tool/Module operation can
  report its own real progress (started/progress/completed/failed,
  with optional hierarchical nesting) through the existing EventBus;
  any Interface can subscribe once and render progress for every
  present and future Tool with zero code change
- **Server Platform** — a long-running Server Runtime
  (`python -m parika.server`) exposing a versioned REST/WebSocket API
  (`/api/v1`) over the same Brain/Planner execution pipeline the CLI
  uses, with pluggable authentication (none/API key/JWT), streaming
  chat over WebSocket, and a generic capability-execution fallback
  endpoint so every registered capability is reachable without an API
  redesign — see "Run PARIKA" below and
  `docs/api/PARIKA_API_Reference.html`

---

## Architecture Overview

Execution pipeline:

```text
User
  ↓
Interface (CLI today; API Layer below for REST/WebSocket/future Desktop/Web/Voice)
  ↓
Brain
  ↓
Planner  ──▶ Requirement Inference (see section 5) ──▶ Intelligent Model Selection (see section 4)
  ↓
TaskManager
  ↓
CapabilityExecutor
  ↓
ToolManager / ProviderManager
  ↓
Tool implementation / Provider implementation (e.g. Ollama)
```

PARIKA has two permanently separate concepts, not one Interface that
will eventually replace the other:

- The **PARIKA Console** (`parika/console/`, the `parika` command /
  `python -m parika`) is PARIKA's native, in-process administration
  console. It calls `Brain.handle()` directly, exactly as shown above
  — it is not, and will never become, a client of the API layer below,
  and is not subject to client authentication or rate limiting.
- The **Server Platform**'s REST/WebSocket **API Layer**
  (`parika/api/`, served by `parika/server/`, versioned at `/api/v1`)
  is for external clients only (Desktop, Web, Android, iOS, Voice, a
  future CLI client — all out of scope today). It dispatches every
  request through the previously-unused `Router` Core component:
  chat/goal-oriented requests reach `Brain`/`Planner` exactly as above;
  read-only/administrative requests (`status`, `tools`, `modules`,
  `capabilities`, `providers`, `config`) go straight to the relevant
  Core manager.

The Console and the API Layer each construct their own `ParikaRuntime`
and never depend on one another — see `docs/guides/Running.md`
section 12 and `docs/architecture/PARIKA_Architecture_Specification_v1.0.md`
("PARIKA Console" section).

Architecture details:

- `docs/architecture/PARIKA_Architecture_Specification_v1.0.md`
- `docs/architecture/Core_Component_Responsibilities.md`
- `docs/architecture/PARIKA_Decision_Flow.md`
- `docs/architecture/Model_Selection_Framework.md`
- `docs/architecture/Request_Understanding.md`
- `docs/architecture/Provider_Tool_Calling.md`
- `docs/architecture/adr/` — architectural decision records

---

## Intelligent Model Selection

When more than one Provider model can satisfy a request, **Planner**
(and only Planner — this never moves to `ProviderManager`, see
`Core_Component_Responsibilities.md`) scores every enabled, available
candidate and picks the best fit, instead of just using the first match:

- **Providers expose metadata** (`ProviderModel.metadata`): capabilities,
  execution features, context window, and optional signals like
  estimated latency, deployment type, and cost — never hardcoded, always
  discovered or self-reported by the Provider.
- **Scoring is rule-based and pluggable** (`ScoringRule` — latency,
  reasoning, tool calling, context window, cost, plus preference bonuses
  for local/streaming/healthier providers), not a hardcoded pile of
  functions. Adding a new dimension means writing one new class.
- **Every weight and preference is TOML-driven**
  (`config/defaults.toml`'s `[model_selection]`), read through the same
  `Configuration` component everything else uses — no parallel config
  system, no code change required to tune behavior.
- **Reasoning/"thinking" is a generic preference**
  (`RequestOptions.reasoning`), resolved from configurable
  `simple`/`normal`/`complex` → `off`/`auto`/`on` rules. Translating it
  into a concrete mechanism (e.g. Ollama's `think` field) happens only
  inside that Provider.
- **Every decision is fully transparent**: DEBUG logs show the
  requirements evaluated, every candidate's score breakdown (or
  rejection reason), and the final choice.

See `docs/architecture/Model_Selection_Framework.md` for the complete
design, `docs/development/Model_Selection_Guide.md` for a contributor
how-to, and `docs/architecture/adr/0001-intelligent-model-selection.md`
for why it is built this way.

---

## Requirement Inference

Before model selection runs, Planner infers what a request actually
needs directly from its message text - so a greeting is no longer
treated the same as *"What is the current time in IST?"*:

- **Deterministic, pattern-based rules** (`InferenceRule`, mirroring
  `ScoringRule`'s pluggable design) decide whether tool calling is
  `NOT_NEEDED`, `PREFERRED`, or `REQUIRED` for a message - never an LLM
  call, never provider-specific logic, and never semantic decomposition
  of the request into multiple Goals.
- **A new built-in Runtime Info Tool** answers date/time questions from
  the real system clock (stdlib `datetime`/`zoneinfo`, no network),
  exactly the way the Web Search Tool already answers news/weather/
  office-holder questions.
- **`REQUIRED` tool calling excludes non-tool-calling models** before
  scoring even runs, so a date/time or "latest news"-style question is
  routed to a model that can actually call a tool, instead of one that
  would guess.

See `docs/architecture/Request_Understanding.md` for the complete
design and `docs/development/Requirement_Inference_Guide.md` for a
contributor how-to.

---

## Repository Structure

```text
docs/
├── architecture/
│   └── adr/
├── development/
├── guides/
└── examples/
```

Other important folders:

- `parika/`
  - `core/` — the frozen Core (Brain, Planner, ProviderManager, ...,
    plus `security/` — transport-agnostic hashing primitives only)
  - `interfaces/` — the reusable Interface layer (session lifecycle,
    request construction, commands, formatting) shared by every
    in-process presentation layer
  - `console/` — the native PARIKA Console: the in-process,
    unrestricted administration REPL (`parika` / `python -m parika`).
    Not an API client -- see "Architecture Overview" below
  - `api/` — the REST/WebSocket API layer (`/api/v1`): schemas,
    routers, handlers (orchestration/translation only, never business
    logic), auth backends, `router_bindings.py` (wires the `Router`
    Core component)
  - `server/` — the Server Runtime (`python -m parika.server`):
    `create_app()`, lifespan wiring, CLI argument parsing
  - `providers/` — Provider implementations (Ollama)
  - `modules/`, `tools/` — Modules and Tools (Web Search, Runtime Info,
    Filesystem, Weather, Currency, News, Chat, Coding, Repository
    Intelligence, Coding Agent)
- `tests/`
- `config/`
- `data/`
- `plugins/`
- `scripts/generate_api_docs.py` — regenerates `docs/api/PARIKA_API_Reference.html`

---

## Prerequisites

- Python 3.14+
- Git
- `uv` (recommended package/environment manager)
- Linux / macOS / Windows
- Ollama (optional, required for local LLM features such as
  `coding.execute_task` and normal model-backed chat)
- NVIDIA GPU driver (optional, required for NVIDIA GPU acceleration/
  telemetry features)
- ZBar system library (optional, required for `vision.detect_qr_codes`
  and `vision.detect_barcodes` when the `vision` extra is installed)

### Platform Notes

- PARIKA can run without Ollama when using capabilities that do not
  require an LLM Provider.
- The `voice`, `vision`, `video`, `gpu`, `server`, `document`, `ocr`,
  `coding`, and `dev` functionality is represented by optional
  dependency groups in `pyproject.toml`.
- For a complete development/runtime installation matching the current
  repository, install all optional dependency groups with `uv sync
  --all-extras`.
- The `requirements.txt` file is an autogenerated compatibility export
  from `pyproject.toml`; do not maintain it manually.
- On Linux, the `vision` QR/barcode capabilities also require the system
  ZBar shared library in addition to the Python `pyzbar` package.

---

## Installation (Steps 1–8)

### Step 1 — Clone the repository

```bash
git clone https://github.com/pushpesh47/parika-server.git
cd parika
```

### Step 2 — Install `uv`

Install `uv` using the official installer for your platform, then open
a new shell if required so that the `uv` command is available.

Verify:

```bash
uv --version
```

### Step 3 — Create the PARIKA environment and install dependencies

PARIKA uses `pyproject.toml` as the dependency source of truth and
`uv.lock` for resolved versions. Do not copy the `.venv` directory from
another machine.

For a complete PARIKA installation, including all currently defined
optional dependency groups:

```bash
uv sync --all-extras
```

This creates or updates `.venv` automatically.

### Step 4 — Activate the virtual environment

Linux / macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

### Step 5 — Verify Python and the installation

```bash
python --version
python -c "import parika"
uv pip freeze
```

Python must be 3.14 or newer.

### Step 6 — Install system ZBar support when using QR/barcode detection

The `vision` extra installs the Python `pyzbar` package, but QR/barcode
decoding also requires the system ZBar shared library.

On Debian/Ubuntu:

```bash
sudo apt install libzbar0
```

On other operating systems, install the equivalent ZBar system library
for that platform.

### Step 7 — Configure Ollama when using local LLM features

Ollama is optional. If local model-backed features are required, install
Ollama separately, start the Ollama service, and make sure at least one
compatible model is installed.

Verify that Ollama is reachable before starting PARIKA.

### Step 8 — Run the test suite

```bash
pytest
```

For verbose output:

```bash
pytest -v
```

### Alternative: install with `pip`

If `uv` is not available, the complete dependency groups can be installed
through the standard Python virtual environment workflow:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,coding,server,ocr,document,vision,video,gpu,voice]"
```

This is a compatibility fallback. `uv sync --all-extras` is the
recommended installation method because it uses the repository's
`pyproject.toml` and `uv.lock`.

### Recreating an environment on another machine

Do not copy `.venv` from the original machine. Clone/copy the repository,
ensure Python 3.14+ is installed, then run:

```bash
uv sync --all-extras
```

The new `.venv` is recreated from the project's dependency definitions
and lockfile.

If the repository has changed its dependencies, regenerate the
compatibility `requirements.txt` from `pyproject.toml` with:

```bash
uv export --all-extras --format requirements-txt --no-hashes -o requirements.txt
```

---

## Run PARIKA

Both of the following start the same interactive CLI:

```bash
parika
python -m parika

or

python -m parika.console
```

```text
$ parika
PARIKA v0.1.0
Type /help for commands, or start chatting. Ctrl+D to exit.

> Hello
Hello! How can I help you today?
```

Features: command history and arrow-key navigation, multiline input,
Markdown rendering, streaming output, native Ollama tool calling, and
built-in slash commands (`/help`, `/status`, `/providers`, `/tools`,
`/capabilities`, `/config`, `/history`, `/reload`, `/version`, `/clear`,
`/exit`).

### Running the Server Platform (REST/WebSocket API)

```bash
pip install -e ".[server]"
python -m parika.server
```

```text
$ python -m parika.server
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

```bash
curl http://127.0.0.1:8080/api/v1/status
curl -X POST http://127.0.0.1:8080/api/v1/chat \
  -H "Content-Type: application/json" -d '{"text": "Hello"}'
```

Interactive API docs are served at `/docs`/`/redoc`; the full generated
reference lives at `docs/api/PARIKA_API_Reference.html`. See
`docs/guides/Running.md` section 12 for authentication modes,
streaming chat over WebSocket, and the generic capability-execution
fallback endpoint. The Console and the Server Platform are
permanently separate (see "Architecture Overview" above) — for
anything besides the Console (a Desktop UI, Web UI, ...), build
against `/api/v1` rather than the internal `parika/console/` or
`parika/interfaces/` packages directly.

---

## Run Tests

```bash
pytest
```

```bash
pytest -v
```

See:

- `docs/guides/Testing.md`

---

## Examples

### Local-only

Run the integration tests, or start the CLI with Ollama running locally
and just chat — no internet required unless you ask something that
triggers `web.search`.

### Internet-enabled

Load the Web Search Module and execute the `web.search` capability
directly, or ask the CLI something that needs current information and
let the model decide to call `web_search` itself (native Ollama tool
calling, resolved through Brain and Planner exactly like any other
request).

Complete examples are in:

- `docs/guides/Running.md`
- `docs/examples/Request_Execution_Examples.md`

---

## Project Configuration

Configuration is loaded from layered TOML files:

```text
defaults.toml
installation.toml
workspace.toml
environment.toml
runtime.toml
```

Notable sections: `[providers.ollama]` (base URL, timeouts, tool-calling
iteration limit), `[interfaces.cli]` (prompt, colors, streaming,
execution-progress rendering — the Console's config namespace, kept
under its historical name for backward compatibility), and
`[model_selection]` (scoring weights, preferences, and reasoning-mode
mapping — see section 4). `[api]`/`[api.auth]`/`[api.cors]`/
`[api.rate_limit]` configure the Server Platform's authentication mode
(none/API key/JWT), bind host/port, CORS, and rate limiting — see
`docs/guides/Running.md` section 12.

### Workspace Permissions

Reading, searching, and inspecting files is always allowed anywhere on
the host; only creating, writing, renaming, moving, deleting, copying,
or running a shell command is confined to trusted workspaces
(`[workspace]`, `[filesystem].trusted_workspaces`, `[shell]`), with an
interactive `Allow once`/`Allow for this session`/`Always trust`/`Deny`
prompt for anything else. The Shell Tool itself is disabled by default
(`[shell].enabled = false`). See `docs/development/Tool_Guide.md`
§22–23 for the Shell Tool and Filesystem Tool configuration keys, and
`docs/architecture/Core_Component_Responsibilities.md` §25 for how
permission decisions and prompting work.

---

## Project Lifecycle

Current lifecycle:

Start → Run → Stop → Restart

Applications embedding PARIKA manage the lifecycle.

---

## Development

### Documentation

Architecture:

- `docs/architecture/`

Development guides:

- `docs/development/Module_Guide.md`
- `docs/development/Tool_Guide.md`
- `docs/development/Capability_Guide_Final.md`
- `docs/development/Integration_Checklist.md`
- `docs/development/Model_Selection_Guide.md`
- `docs/development/Requirement_Inference_Guide.md`
- `docs/development/Provider_Tool_Calling_Guide.md`

Operational guides:

- `docs/guides/Running.md` (section 12: Server Platform / REST/WebSocket API)
- `docs/guides/Testing.md`

API reference (generated, kept separate from architecture docs):

- `docs/api/PARIKA_API_Reference.html` — regenerate with
  `python scripts/generate_api_docs.py`

---

## Troubleshooting

Common issues:

- Python not installed
- Virtual environment not activated
- Dependencies missing
- Test failures
- Network restrictions
- Missing Provider or Tool

---

## Known Limitations

- Workflow execution incomplete
- Some future components remain placeholders (MemoryManager,
  KnowledgeManager, ContextManager not yet wired into the request
  pipeline)
- Default Web Search backend may be blocked on some networks
- `enable_dynamic_latency_learning` / `enable_dynamic_performance_learning`
  (`[model_selection]`) are recognized configuration flags without a
  wired learning implementation yet — see `Model_Selection_Framework.md`
  section 11
- Only one Provider (Ollama) ships today; the framework is designed for
  more, but none are implemented yet
- Requirement Inference uses deterministic pattern matching, not true
  language understanding — unanticipated phrasings may not be
  recognized (see `Request_Understanding.md`)
- One locally installed model was observed emitting a malformed
  tool-call as plain text when multiple tools were advertised at once
  — a model/template quirk, not a PARIKA defect, and now automatically
  recovered by a generic fallback parser (see `Running.md` section 10.4
  and `Provider_Tool_Calling.md`)
- Any model can occasionally produce a blank final answer; PARIKA
  retries once automatically, but a persistently unreliable model is
  better excluded via `[model_selection.weights]` than compensated for
  with more retries (see `Provider_Tool_Calling.md` section 5)
- The Filesystem Tool has no `trusted_workspaces` configured by default
  beyond `[workspace].default_workspace` (`data/`); every mutating/
  destructive path outside the trusted set requires an interactive
  decision (or a headless run denies it, since there is no prompt to
  answer) - widen `[filesystem].trusted_workspaces` to grant access
  elsewhere without prompting
- The Shell Tool is disabled by default (`[shell].enabled = false`) -
  set it to `true` (or the legacy `[security].allow_shell_commands`)
  to enable `shell.execute`/`background`/`processes`/`kill`
- The Coding Tool's deep symbol/reference/call-hierarchy analysis is
  fully implemented for Python only (stdlib `ast`); every other of the
  16 target languages needs the optional `coding` dependency group
  (`pip install parika[coding]`, Tree-sitter) for structural symbol/
  import extraction — without it, those languages fall back to a
  generic TODO/FIXME-only analyzer, never a crash. Symbol/call
  resolution everywhere is a deliberate, coarse heuristic (matching by
  plain name across the index), not full semantic/type-aware
  resolution
- `coding.execute_task` (the Coding Agent) requires a working LLM
  Provider (Ollama) to decompose a request into a plan
  (`coding.plan_change`); without one running, the Goal still plans
  and executes through Brain/Planner/TaskManager exactly as designed,
  but fails gracefully (reported through `BrainResponse`, never a
  crash) rather than producing a plan
- Repository Intelligence's Project Awareness detectors
  (framework/package-manager/build-system/test-framework/linter/
  formatter) use lightweight, deterministic manifest-file heuristics
  per ecosystem, not a full build-tool integration
- `shell.execute`/`shell.background` have no output streaming - a
  synchronous `ToolRequest -> ToolResponse` call has no channel for
  partial output; use `shell.background` + polling `shell.processes`
  for long-running commands
- Execute permission authorizes running a command from a workspace
  only - it never parses or restricts what that command does once
  running (see `docs/development/Tool_Guide.md` section 22.2)
- "Allow for this session" and the in-memory effect of "Always trust"
  both last for the lifetime of the current process - today, one CLI
  process hosts exactly one session, so this is exact; a future multi-
  session server entry point would need its own per-session handling
- Currency rates: Frankfurter's ECB-anchored coverage does not include
  every possible currency pair; `open.er-api.com` is an automatic
  failover for wider coverage, but neither provider requires an API
  key
- News: `news.latest`/`news.topic` depend on a small, curated,
  operator-overridable set of public RSS feeds staying reachable and
  unchanged; `news.search` (and any unconfigured topic) depends on
  Google News' public RSS search endpoint remaining available
- The Console (`parika/console/`) does not call the Server Platform's
  API, by design — it is PARIKA's native, unrestricted administration
  console, not an external client, and constructs its own in-process
  `ParikaRuntime` directly (see "Architecture Overview" above). The
  API server's interactive workspace-permission prompting and
  multi-session-scoped permission grants are not yet implemented.
  Every capability is nonetheless already reachable today by any
  external client through `/api/v1`, including the generic
  capability-execution fallback endpoint for anything without its own
  dedicated endpoint yet
- Execution-progress events (Phase 3.5b: `brain.execution.*`,
  `memory.search.*`, `knowledge.search.*`, and the existing
  `capability.execution.*`/`tool.executed` events) render live in the
  Console today, since it shares the same in-process `EventBus`.
  Exposing them over REST/WebSocket is deferred: the WS chat handler
  already buffers tokens rather than truly interleaving them
  (`parika/api/ws/chat.py`, see `docs/guides/Running.md` section 12)
  because of a SQLite thread-safety constraint, and shipping buffered
  execution-progress events would misrepresent them as live
- `[api.rate_limit]` is configuration-only today; no rate-limiting
  middleware is enforced yet

---

## Contributing

Before contributing:

1. Read the architecture documentation.
2. Follow the coding standards.
3. Add tests.
4. Keep pull requests focused.

---

## License

License to be finalized.
