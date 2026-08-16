# Testing PARIKA

**Status:** Reference documentation for running and writing tests.

------------------------------------------------------------------------

# 1. Test Runner

PARIKA uses [`pytest`](https://docs.pytest.org/), installed via the `dev`
optional dependency group:

```bash
uv pip install -e ".[dev]"
```

`pyproject.toml` configures `testpaths = ["tests"]`, so running `pytest`
from the repository root discovers every test automatically:

```bash
pytest
```

Run a single package's tests:

```bash
pytest tests/core/task_manager/
pytest tests/tools/web_search/
pytest tests/integration/
```

Run with verbose output:

```bash
pytest -v
```

------------------------------------------------------------------------

# 2. Test Layout

Tests mirror the source tree under `tests/`. One subdirectory exists per
Core component, per Module, per Tool, and per Provider — this list is a
package-level map, not an exhaustive file listing (individual test files
are called out in the sections below where they matter):

```text
tests/
├── core/                  one directory per Core component, e.g.:
│   ├── brain/              (includes brain/context_engine/)
│   ├── capability_executor/
│   ├── capability_registry/
│   ├── capability_resolver/
│   ├── configuration/
│   ├── context_manager/
│   ├── event_bus/
│   ├── health_manager/
│   ├── knowledge_manager/
│   ├── lifecycle_manager/
│   ├── logger/
│   ├── memory_manager/
│   ├── metrics_manager/
│   ├── module_manager/
│   ├── permission_manager/
│   ├── planner/            (includes model_selection/)
│   ├── policy_engine/
│   ├── provider_manager/
│   ├── resource_manager/
│   ├── router/
│   ├── scheduler/
│   ├── security/           (Server Platform - hashing primitives only, see §5.8)
│   ├── service_container/
│   ├── state_manager/
│   ├── task_manager/
│   ├── tool_manager/
│   ├── update_manager/
│   └── workflow_engine/
├── modules/                one directory per Module, e.g.:
│   ├── chat/, currency/, experience/, filesystem/,
│   ├── knowledge_indexing/, memory/, news/, runtime_info/,
│   └── weather/, web_search/
├── tools/                  one directory per Tool, e.g.:
│   ├── currency/, filesystem/, memory/, news/, runtime_info/,
│   └── weather/, web_search/ (search backends, dedup, ranking, cache,
│       driver, page fetcher, transport — see §5.1)
├── providers/
│   └── ollama/             (transport, driver, wire, streaming, tool
│                            calling, transparency — see §5.1-5.3)
├── interfaces/
│   ├── commands/, formatting/
│   └── test_runtime.py, test_session*.py, test_chat_capability.py, …
├── console/                 The native PARIKA Console's own tests
│                            (formerly tests/interfaces/cli/)
├── server/                 Server Runtime lifespan/entrypoint tests (see §5.8)
├── api/                    REST/WebSocket API layer tests (see §5.8)
│   ├── auth/, routers/, ws/
│   └── test_error_mapping.py, test_router_bindings.py, …
└── integration/
    ├── test_web_search_pipeline.py
    ├── test_chat_pipeline.py
    ├── test_runtime_info_pipeline.py
    ├── test_new_tools_pipeline.py
    ├── test_context_assembly_pipeline.py
    └── test_tool_calling_framework.py
```

`tests/core/planner/model_selection/` (unit tests for the Intelligent
Model Selection Framework) and
`tests/core/planner/test_planner_model_selection.py` (Planner-level
multi-candidate integration) are covered in section 5.5.
`tests/core/planner/requirement_inference/` and
`test_planner_requirement_inference.py` no longer exist: Planner's
former Requirement Inference framework has been removed as part of the
AI Context Engineering migration (see
`docs/architecture/Request_Understanding.md`); section 5.6 now covers
its live-pipeline successor coverage instead.
`test_tool_calling_framework.py` (the generic, framework-driven
validation suite) is covered in section 5.3.

------------------------------------------------------------------------

# 3. Unit Tests

Unit tests exercise a single component's public API. Every Core component
implemented in this project follows the same coverage shape mandated by the
Coding Standards:

- **Normal behavior** — the component does what its docstring promises.
- **Invalid input** — malformed requests raise the component's own
  dedicated exception types.
- **Failure scenarios** — dependency failures are handled the way the
  component's responsibilities dictate (raised, wrapped, or captured).
- **Events** — every documented event is asserted to be published with the
  correct payload, using `EventBus.subscribe()`.
- **Lifecycle / state transitions** — every legal and illegal state
  transition is exercised (e.g. `TaskManager`, `LifecycleManager`,
  `Scheduler`, `UpdateManager`).
- **Edge cases** — empty collections, duplicate registrations, missing
  optional dependencies, and similar boundary conditions.

## Test doubles

Two dependencies deserve special mention:

- **`Logger`** — most tests use a small fake exposing only
  `get_logger(name) -> logging.Logger`. `ToolManager` and `ProviderManager`
  perform a strict `type(x) is Logger` check in their constructors, so
  tests that construct these two managers must use a real
  `Logger(Configuration())` instance instead of a fake.
- **`EventBus`** — real `EventBus` instances are cheap to construct and are
  used directly in almost every test, with `RecordingSubscriber` helper
  classes used to capture published events for assertions.

Network-facing code (the Web Search Tool) is tested by substituting a fake
`HttpTransport` (see
[`../development/Tool_Guide.md`](../development/Tool_Guide.md)) rather
than mocking `urllib` internals directly, except in
`tests/tools/web_search/test_transport.py`,
which patches `urlopen` specifically to verify `UrllibHttpTransport`'s own
translation logic for timeouts, HTTP errors, and other network failures.

**Testing concurrency-sensitive components deterministically:**
`Scheduler` runs callbacks on real background threads
(`threading.Timer`), so a test that wants to observe "the callback is
currently executing" (`JobStatus.RUNNING`) must never rely on
wall-clock sleeps/delays to line up with a background thread's
timing — under load (e.g. many other tests spinning up short-lived
threads immediately beforehand), a delay-based race can flip either
way non-deterministically. `tests/core/scheduler/test_scheduler.py`'s
`test_cancel_raises_when_job_is_currently_running` and
`test_shutdown_leaves_an_already_running_job_running` instead
synchronize on a `threading.Event` the callback itself sets the
instant it starts running, so the main test thread only proceeds to
call `cancel()`/`shutdown()` once the job is verifiably `RUNNING` —
deterministic regardless of system load. Prefer this pattern over a
`time.sleep()` guess whenever a test needs to observe a specific
in-flight concurrency state.

------------------------------------------------------------------------

# 4. Integration Tests

`tests/integration/test_web_search_pipeline.py` exercises the complete,
real execution pipeline:

```text
Brain -> Planner -> TaskManager -> CapabilityExecutor ->
ToolManager -> Web Search Tool -> Internet
```

Every Core component in this chain is real and fully wired (the same way
[`Running.md`](Running.md) bootstraps them). Only the outermost network
boundary — `HttpTransport` — is replaced with a deterministic fake, so the
suite never depends on real network access while still exercising every
other component exactly as it runs in production.

The suite covers:

- **Successful execution** — a well-formed `web.search` Goal returns parsed
  results end to end.
- **Network failure** — a persistent `WebSearchNetworkError` propagates
  through `ToolExecutionError` → `CapabilityExecutionError` →
  `TaskExecutionError` and is captured in the `GoalResult`, without Brain
  raising.
- **Timeout** — a persistent `WebSearchTimeoutError` behaves identically.
- **Retry** — a single transient timeout followed by success demonstrates
  that the Web Search Tool's retry handling recovers within the full
  pipeline (verified by asserting the fake transport was called twice).
- **Cancellation** — a Task cancelled via `TaskManager.cancel()` before
  `execute()` is called never reaches the Tool driver at all.
- **Invalid requests** — a Goal missing a required argument, and a Goal
  referencing an unknown Capability, both fail gracefully and are reported
  in the `BrainResponse` rather than raised.

`tests/integration/test_chat_pipeline.py` exercises the equivalent, longer
chain introduced by the Ollama provider and the Interface layer:

```text
Brain -> Planner -> TaskManager -> CapabilityExecutor -> ProviderManager ->
Ollama Provider -> (tool calling: Brain again) -> Planner -> TaskManager ->
CapabilityExecutor -> ToolManager -> Web Search Tool
```

Every Core component, the Chat Module, the Web Search Module, and the real
`OllamaProviderDriver` are wired exactly as `build_default_runtime()` wires
them; only the two outermost network boundaries — the Ollama
`OllamaTransport` and the Web Search Tool's `HttpTransport` — are replaced
with deterministic fakes. The suite covers:

- **Direct answers** — a `chat.respond` Goal with no tool call flows
  through the full pipeline and returns the model's answer.
- **Successful tool calling** — a scripted Ollama response requesting
  `web_search` is resolved by calling `Brain.handle()` (never `ToolManager`
  directly), the resulting `ToolResponse` is fed back to a second scripted
  Ollama turn, and the final answer plus a recorded `OllamaToolInvocation`
  are both returned.
- **Tool failure recovery** — a persistent `WebSearchNetworkError` is fed
  back to the model as an error message rather than raised, and the model
  still produces a final answer.

## Live verification (not part of the automated suite)

The Web Search pipeline has additionally been verified against a **real,
locally running Ollama instance** and the **real internet**, as described
in [`Running.md`](Running.md) section 6. The full chat/tool-calling
pipeline described above, including native Ollama tool calling and token
streaming, has likewise been verified end to end against a real, locally
running Ollama instance and the real internet through the `parika` CLI
itself (see [`Running.md`](Running.md) sections 8.3 and 8.5). That
verification is intentionally kept outside the committed `pytest` suite
because it depends on external, non-deterministic services (a running
Ollama daemon and live internet access) and is not suitable for repeatable
CI execution.

------------------------------------------------------------------------

# 5. Provider, Streaming, Tool-Calling, and CLI Tests

## 5.1 Provider Tests

`tests/providers/ollama/` covers the Ollama provider driver in isolation:

- **`test_ollama_transport.py`** — `UrllibOllamaTransport`'s translation of
  successes, HTTP errors (including the "model not found" 404 shape),
  timeouts, other network failures, and streamed NDJSON responses.
  `urllib.request.urlopen` is patched so no real network I/O occurs,
  mirroring `tests/tools/web_search/test_transport.py`.
- **`test_model_mapping.py`** — capability/execution-feature/limit
  derivation from real-shaped Ollama `/api/show` payloads.
- **`test_messages.py`** — `OllamaMessage`/`OllamaToolCall`/`OllamaToolSpec`
  wire-payload serialization.
- **`test_manifest.py`** — the Ollama `Provider` descriptor factory.
- **`test_ollama_driver.py`** — `OllamaProviderDriver` against a
  `FakeOllamaTransport` test double: model discovery, health/availability,
  `execute()` dispatch, `generate()` (streamed and non-streamed),
  `chat()` without tools, and `"model not found"` translation.

### 5.1a Web Search Provider Failover

See [`Tool_Guide.md`](../development/Tool_Guide.md) §18 for the design
this coverage validates.

- **`test_search_backend_google.py`**, **`test_search_backend_bing.py`**,
  **`test_search_backend_duckduckgo.py`**, **`test_search_backend_mojeek.py`**,
  **`test_search_backend_qwant.py`** — each HTML-scraping `SearchBackend`
  implementation against a fake `HttpTransport`: result parsing,
  `max_results` limiting, no-results handling, invalid input, and
  retry/timeout behavior, all sharing the same test shape (one file per
  provider, following the `search_backend_<provider>.py` naming
  convention - see `Tool_Guide.md` §18.1). `test_search_backend_google.py`
  additionally covers `TestModernLayoutRobustness` - the parser keeps
  working when every class it previously depended on is renamed (Issue
  3), including a generic-text snippet fallback and ignoring
  navigation/pagination links. `test_search_backend_bing.py`
  additionally covers `TestDecodeBingRedirect` (decoding
  `bing.com/ck/a?...&u=...` click-tracking redirects into the real
  destination URL, Issue 5) and `TestRealWorldMarkupRobustness` (a
  leading breadcrumb/citation row rendered before the `<h2>` title no
  longer corrupts the extracted title, and `display_url` is exposed
  separately - Issues 4 and 8).
- **`test_search_backend_google_cse.py`** — `GoogleCseSearchBackend`
  against a fake `HttpTransport` returning JSON: result parsing,
  `max_results` limiting, `WebSearchProviderUnavailableError` when
  invoked without an API key or Search Engine ID (and that no request
  is attempted in that case), HTTP-error and malformed-JSON handling,
  and retry/timeout behavior.
- **`test_web_search_config.py`** — `load_web_search_config()`: built-in
  defaults when `Configuration` is `None` or `[web_search]` is absent
  (a single provider - Google - never a multi-provider failover, see
  `config.DEFAULT_PROVIDER_ORDER`'s docstring), reading
  `enabled`/`default_provider`/`provider_order`/`[web_search.google_cse]`,
  and `WebSearchProviderConfig.failover_order()`'s
  default-provider-first, no-duplicates ordering.
- **`test_search_backend_failover.py`** — `FailoverSearchBackend` in
  isolation, against scripted `SearchBackend` doubles: the first
  successful provider's result wins; failover continues past multiple
  consecutive failures; a clean `WebSearchAllProvidersFailedError`
  (naming every provider that failed) is raised only once every
  provider has failed; and `InvalidSearchQueryError` propagates
  immediately without trying any provider.
- **`test_provider_registry.py`** — `provider_registry.py`: every
  provider named in `config.DEFAULT_PROVIDER_ORDER`/
  `config/defaults.toml` is actually registered; every no-configuration
  provider is always available and builds the expected backend type;
  `google_cse` reports itself unavailable without both credentials and
  available with both; `build_search_backend()` returns a single
  available provider's backend **directly** (proving backward
  compatibility: its exceptions propagate unwrapped) versus a
  `FailoverSearchBackend` when two or more are available;
  unrecognized-**and**-unavailable-provider-name skipping (a factory
  for a skipped provider must never even be called); and raising when
  no configured provider is both recognized and available.
- **`test_ranking.py`** — `ranking.rank_results()`: empty input;
  order preserved when nothing matches the query; a highly relevant
  result reported near the end of the backend's own order is promoted
  ahead of a barely-relevant one placed first (Issue 6/7); title
  overlap outweighs snippet overlap; ties are stable (preserve backend
  order); custom weights are honored; case-insensitive matching; and
  common stopwords never drive relevance on their own.
- **`test_driver.py`** additionally covers the full three-stage
  Provider → Ranking → Result Selection pipeline: the backend is
  always asked for the configured candidate pool size, not just the
  final requested count; the pool grows with a larger explicit
  `max_results`; ranking promotes a relevant low-ranked result ahead
  of truncation; `ranking_enabled=False` preserves raw backend order;
  and `default_max_results` is configurable.
- **`test_web_search_module.py::TestConfigurationDrivenBackendSelection`** —
  `WebSearchModuleDriver` end to end: no `Configuration` still defaults to
  a single `GoogleHtmlSearchBackend` (exactly one HTTP request, just
  against the new default provider); a `Configuration` shaped like the
  real, shipped `config/defaults.toml` fans out into a full
  `FailoverSearchBackend`, Google first; an explicit `search_backend`
  always overrides configuration-driven selection; `google_cse` in
  `provider_order` without credentials is skipped automatically (falling
  back to the next provider) and used once credentials are configured;
  and `[web_search].enabled = false` registers neither the Capability
  nor the Tool at all (and unloading such a never-registered module is
  a clean no-op).

## 5.2 Streaming Tests

Streaming is covered at two levels:

- `test_ollama_driver.py::TestGenerate::test_streamed_generate_invokes_on_token`
  and `TestChatWithoutTools::test_streamed_chat_invokes_on_token_for_final_answer`
  assert that `on_token` is invoked once per streamed NDJSON chunk and that
  the accumulated text matches the concatenation of every fragment.
- `tests/console/test_streaming.py` covers `StreamingPrinter` (the
  Console's `on_token` sink) writing and flushing each fragment
  immediately.
- `tests/console/test_app.py::TestChat::test_streaming_chat_prints_tokens_live`
  covers the Console application wiring a streaming callback into
  `InterfaceSession.submit_text()` end to end.

### 5.2a Streaming Protocol Filter (leaked tool-call markup)

See [`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md)
§11.1 for the design this coverage validates.

- **`test_stream_filter.py`** — `ToolMarkupStreamFilter` in isolation:
  ordinary text passes through immediately; XML-style and Hermes-style
  markup (including a hint deliberately split across several `feed()`
  calls) never reaches the sink; genuine preamble text before markup
  still streams live; a suspected-but-never-completed markup prefix is
  released via `flush()`; suppression state never leaks between
  instances.
- **`test_ollama_driver.py::TestStreamedLeakedMarkupSuppression`** —
  the same guarantee end to end through `OllamaProviderDriver.chat()`:
  leaked markup (split across chunks) never reaches `on_token`, while a
  normal streamed answer with tools available is completely unaffected.
- **`test_ollama_driver.py::TestDuplicateResponsePrevention`** — a
  tool-calling turn's `content` is always cleared, even when native
  `tool_calls` arrive alongside non-empty accompanying text, so exactly
  one assistant response is ever produced per turn (Priority 3).
### 5.2b Reasoning Markup Suppression

See [`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md)
§12 for the design this coverage validates.

- **`test_reasoning_markup.py`** — `strip_reasoning_markup()`:
  `<think>`/`<reasoning>` block removal, case-insensitivity, an
  unterminated block at end of string, ordinary content unchanged.
- **`test_ollama_driver.py::TestReasoningMarkupSuppression`** — full
  driver-level coverage: a `<think>` block never reaches `on_token`
  even with no tools offered at all; the block is stripped from a
  non-streamed final answer; a block split across multiple chunks is
  suppressed; and genuine answer text *after* a closed block still
  streams live in the same turn (unlike leaked tool-call markup,
  which suppresses for the rest of the turn once confirmed).

- **`test_session.py::test_tool_calling_round_trip_appends_exactly_one_assistant_entry`** —
  end-to-end confirmation through a real `ParikaRuntime` that a tool
  round trip still appends exactly one `HistoryRole.ASSISTANT` entry.

## 5.3 Tool-Calling Tests

Native Ollama tool calling — resolving a model's `tool_calls` by calling
`Brain.handle()`, never `ToolManager` directly — is covered at four
levels, from narrowest to broadest. See
[`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md)
for the design this coverage validates.

- **`test_wire.py`** and **`test_text_tool_calls.py`** — native
  `tool_calls` field parsing (including the JSON-string-arguments
  variant some templates emit) and the generic text-based fallback
  parser (Hermes/ChatML `<tool_call>{...}</tool_call>` and XML-style
  `<function=NAME><parameter=KEY>VALUE</parameter></function>`),
  including the exact malformed content reproduced from a real Ollama
  server (`qwen3-coder:latest`, two tools advertised).
- **`test_ollama_driver.py::TestChatToolCalling`** exercises the driver's
  tool-calling loop against a real `Brain`/`Planner`/`TaskManager`/
  `ToolManager` stack (only the innermost `ToolDriver` is scripted):
  successful calls, tool failures fed back as error messages, unknown tool
  names, a driver with no Brain bound, and exceeding
  `max_tool_iterations`. **`TestEmptyFinalResponseRetry`** covers the
  bounded empty-final-response retry, including proof that it never
  consumes the separate `max_tool_iterations` budget.
- **`tests/integration/test_tool_calling_framework.py`** — the
  **framework-driven** validation suite added by the backend
  stabilization milestone: every scenario uses synthetic,
  generically-named fixtures (`capability.alpha`/`tool_alpha`,
  `capability.beta`/`tool_beta`) registered directly against the real
  Core stack, deliberately never a real, specific capability, so the
  suite proves the *orchestration framework* is correct independent of
  which Tool-backed capability exercises it. Covers: no-tool-needed
  requests, a single tool's full round trip (including fallback
  recovery and JSON-string arguments), two simultaneous tool calls in
  one turn, two sequential tool calls across turns, conversation
  continuity (message-history shape, and a second independent Goal
  after a prior tool-calling turn), and every failure scenario (tool
  execution failure, unknown tool, an "invalid" call dispatched anyway,
  Provider connection failure, Provider timeout, exceeding
  `max_tool_iterations`, and partial multi-tool failure).
- **`tests/integration/test_chat_pipeline.py::TestChatWithToolCalling`**
  and **`test_runtime_info_pipeline.py`** exercise the same loop through
  the full, real Core stack with a real, specific capability (Web
  Search, Runtime Info respectively) - capability-specific regression
  coverage, unmodified by this milestone.
- `tests/interfaces/test_chat_capability.py` and
  `tests/interfaces/test_session.py` cover building the advertised tool
  specifications and the session-level conversation history update after
  a tool-calling turn.

### 5.3a Repeated Deterministic Tool-Failure Deduplication

See [`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md)
§11.3 for the design this coverage validates.

- **`test_chat_loop.py`** — `run_chat_loop()` with a scripted
  `ToolCallResolver` stand-in: an identical repeat of an already-failed
  call is never re-executed (the cached failure is fed back instead);
  a genuinely different set of arguments always executes, even for the
  same tool name; a repeated *successful* call is never short-circuited
  (deduplication only ever applies to failures); and the existing
  `max_tool_iterations` budget still terminates the loop when the model
  keeps repeating the same failing call regardless.
- **`test_tool_calling.py`** — `ToolCallResolver.resolve()`'s
  unknown-tool recovery now reports every currently available tool name
  (read generically, never hardcoded) alongside the error, so a model
  that hallucinated a tool name can self-correct on its next turn.

## 5.4 Console Tests

`tests/console/` covers the native PARIKA Console itself (formerly
`tests/interfaces/cli/`):

- **`test_colors.py` / `test_markdown.py`** — ANSI colorizing and the
  terminal Markdown renderer (headings, lists, code blocks, inline
  bold/italic/code).
- **`test_progress_view.py`** — `ConsoleProgressRenderer` (Phase
  3.5b): rendering of `progress.*`, `capability.execution.*`, and
  `tool.executed`/`tool.execution_failed` events, indentation by
  `progress_path` depth, unknown-`source_id` fallback labeling, and
  `start()`/`stop()` (un)subscription.
- **`test_app.py::TestExecutionProgressWiring`** — the Console wires
  `ConsoleProgressRenderer` only when the runtime exposes an
  `event_bus`, starts it for the REPL's lifetime, and stops it once
  `run()` returns.
- **`test_streaming.py`** — `StreamingPrinter`.
- **`test_app.py`** — `CliApplication`'s REPL control flow: slash-command
  dispatch, `/exit`/`/clear` behavior, streamed and non-streamed chat
  turns, multiline input continuation (`\` line continuation), and
  graceful `Ctrl+C`/`Ctrl+D` handling — exercised with `builtins.input`
  monkeypatched to replay scripted input and a fake `InterfaceSession` so
  no real runtime or network access is required.

`tests/interfaces/commands/` and `tests/interfaces/formatting/` cover every
built-in slash command and the response/error formatting helpers against a
real `ParikaRuntime` (Ollama connectivity faked). `tests/interfaces/`
top-level covers `build_default_runtime()`/`shutdown_runtime()` and
`InterfaceSession`.

## 5.5 Intelligent Model Selection Tests

See [`Model_Selection_Framework.md`](../architecture/Model_Selection_Framework.md)
for the design this suite verifies.

`tests/core/planner/model_selection/` covers each piece of the framework
in isolation:

- **`test_requirements.py`** — category-derived defaults, and every way
  `Goal.metadata["execution_requirements"]` can override them (a full
  `ExecutionRequirements` instance, a plain dict with string enum
  values, unknown/ignored keys).
- **`test_config.py`** — `load_model_selection_config()` reading
  through a `Configuration`-shaped test double (never real TOML files,
  so overrides are exercised deterministically), falling back to
  built-in defaults for `None`, missing sections, and unknown weight/
  preference/reasoning keys.
- **`test_rules.py`** / **`test_preference_rules.py`** — every built-in
  `ScoringRule`: `LatencyRule`/`ContextWindowRule`/`CostRule` relative
  normalization, `ReasoningRule`'s COMPLEX/NORMAL/SIMPLE direction,
  `ToolCallingRule`'s REQUIRED/PREFERRED/NOT_NEEDED behavior, and every
  preference bonus rule's on/off/unsatisfied combinations.
- **`test_filtering.py`** — every hard-requirement rejection reason
  (disabled/unavailable provider, missing capability, unmet REQUIRED
  tool-calling/vision/structured-output, insufficient context window)
  and every acceptance path.
- **`test_selector.py`** — the full pipeline: no candidates, only
  incompatible candidates, `evaluated_candidates` including both
  accepted and rejected entries (never silently dropped), deterministic
  highest-score selection and tie-breaking, and `ThinkingMode`
  resolution for each `ReasoningLevel`.

`tests/core/planner/test_planner_model_selection.py` adds Planner-level,
multi-candidate integration coverage that
`tests/core/planner/test_planner.py` (unmodified by this framework, still
passing) does not exercise: selecting the lower-latency of two real
candidates, excluding a model missing a required capability, excluding an
unavailable provider, injecting `RequestOptions.reasoning` onto a real
`ProviderRequest` for `COMPLEX`/`SIMPLE` requirements, and confirming a
`provider_request_builder` that returns something other than a
`ProviderRequest` (already exercised by the unmodified test file) is left
untouched by that injection.

`tests/providers/ollama/test_latency_estimation.py` and
`test_ollama_driver.py::TestReasoningPassthrough` cover the Provider side:
parameter-size parsing, the reasoning-capability latency multiplier, and
the generic `RequestOptions.reasoning` -> Ollama's `think` field
translation for both `/api/chat` and `/api/generate`.

## 5.6 AI Context Engineering / Capability Discovery Tests

See [`Request_Understanding.md`](../architecture/Request_Understanding.md)
for the design this suite verifies. Planner's former Requirement
Inference framework (`parika/core/planner/requirement_inference/`) and
`tests/core/planner/requirement_inference/`,
`tests/core/planner/test_planner_requirement_inference.py` have been
removed together; this section now covers what replaced them.

`tests/core/planner/model_selection/test_requirements.py`'s
`TestBuildExecutionRequirementsOverride` class covers Planner's side:
no override produces the neutral category default, a message present
in `goal_inputs["message"]` is never read for inference (it has no
effect), an explicit dict override sets `tool_calling` directly, a
partial override leaves every other field at its category default,
and a full `ExecutionRequirements` instance override is used as-is.

`tests/interfaces/test_chat_capability.py`'s `TestDiscoverToolSpecs`
covers both Automatic Capability Discovery and the only filtering AI
Context Engineering still performs: every enabled TOOL-category
Capability is advertised with its own Tool Affordance Contract
composed into its description (a well-known Capability's own contract
fields render as `Use when:`/`Avoid when:` sections; an unknown
Capability still gets a permissive generic schema; a disabled
Capability is excluded); an ordinary message advertises every enabled
Capability except `memory_remember`; an explicit memory request
advertises `memory_remember`; an identity question excludes every
memory tool but still advertises every non-memory Capability; and a
disabled Capability is never reintroduced by the gate. Its
`TestMemoryRememberToolAffordanceContract` class covers the Tool
Affordance Contract fields that now carry Strictly Explicit Memory
guidance (moved out of AI Context Engineering's own `behavior.py`),
both directly and via the actual composed tool-spec description. Its
`TestBuildChatGoal` class covers the structural (non-text-based)
`tool_calling="preferred"` signal: present whenever `tools` is
non-empty, absent when it is empty, never dependent on message
content. Its `TestBuildAssistantSystemPrompt` class additionally
covers the general Reasoning Policy text now included in the composed
system prompt.

`tests/tools/runtime_info/` and `tests/modules/runtime_info/` cover the
Runtime Info Tool/Module: timezone resolution (IANA names, abbreviations
including `IST`, invalid names), that the reported time reflects the real
system clock, and the Module's registration/health/unregistration lifecycle
(mirroring `tests/modules/web_search/`'s suite).

`tests/integration/test_runtime_info_pipeline.py` exercises the full, real
Core stack (Brain, Planner, TaskManager, CapabilityExecutor, ProviderManager,
the real Ollama provider driver, ToolManager, and the real Runtime Info Tool
reading the real system clock) with only the Ollama transport faked - mirroring
`test_chat_pipeline.py`'s shape - proving a scripted tool call for
`get_current_datetime` is resolved through `Brain.handle()` (never bypassing
Planner) end to end, and that a Goal without an explicit
`execution_requirements` override still executes successfully under the
neutral category default.

`tests/integration/test_context_assembly_pipeline.py`'s
`TestToolAdvertisementFiltering` class is the live-pipeline proof of
Automatic Capability Discovery: through `InterfaceSession.submit_text()`,
a greeting, an identity question, and a weather question all advertise
the full enabled-Capability roster (minus the memory-authorization
gates), inspecting the actual `tools` array sent in the `/api/chat`
HTTP payload.

## Live verification (historical, Requirement Inference era)

Previously verified against a real, locally running Ollama instance:
`qwen3:8b` correctly called `get_current_datetime(timezone="IST")` for
*"What is the current time in IST?"* and produced the real system time
in its final answer, rather than guessing. This scenario is still
covered by `test_runtime_info_pipeline.py` under the current design
(see `Running.md` section 10).

------------------------------------------------------------------------

# 5.7 Observability and Public API Stability Tests

See [`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md)
sections 8–9 for the design this coverage validates.

- **`test_transparency.py`** — every DEBUG-logging helper used by the
  Ollama driver (advertised tool names, native tool call counts,
  execution timing), using `caplog` to assert on the exact rendered
  message, not just that a call didn't raise.
- **`test_planner_observability.py`** — `Planner.plan()`'s additive
  planning-duration and generated-plan-steps logging (kept in its own
  file rather than touching the frozen `test_planner.py`).
- **`test_tool_calling_framework.py::TestFailureScenarios`** doubles as
  the Error Reporting API-stability check: it walks
  `GoalResult.failure.__cause__` to the root Provider/Tool-specific
  exception, documenting and verifying that `TaskManager`'s generic
  top-level wrapper message is by design, not a defect - the specific
  cause is always reachable via standard Python exception chaining.

## Live verification (Provider Tool Calling Hardening)

Additionally verified against a real, locally running Ollama instance
(see `Running.md` section 11): the exact malformed
`qwen3-coder:latest` output that originally motivated this milestone
was reproduced via direct API calls, confirmed fixed end to end through
the real driver (recovered via the text-based fallback, tool executed,
correct final answer produced), and an observed empty-final-response
case was reproduced in a live multi-turn CLI session and confirmed
fixed by the bounded retry on a subsequent run.

------------------------------------------------------------------------

# 5.8 Server Platform (REST/WebSocket API) Tests

See [`Running.md`](Running.md) section 12 for the Server Platform
itself. Requires the `server` extra (`pip install -e ".[server,dev]"`)
— these tests are skipped/absent from a base install and never affect
whether the rest of the suite passes.

- **`tests/core/security/test_hashing.py`** — the transport-agnostic
  `hash_secret()`/`verify_secret()`/`constant_time_equals()`
  primitives, in isolation.
- **`tests/server/test_app_lifespan.py`** — `create_app()`'s
  `lifespan` builds exactly one `ParikaRuntime` per app instance,
  `/api/v1/health`/`/live` answer before that runtime exists,
  `/api/v1/ready` reports `503` until it does, and `shutdown_runtime()`
  runs on teardown.
- **`tests/api/auth/test_backends.py`** — every `AuthenticationBackend`
  (`none`/`api_key`/`jwt`) exercised directly, without HTTP, including
  expiry and wrong-secret rejection.
- **`tests/api/routers/`** — one file per domain router
  (`status`/`tools`/`modules`/`capabilities`/`providers`/`config`/
  `chat`), using `fastapi.testclient.TestClient` (no real socket) against
  a real, isolated `ParikaRuntime` (Ollama model discovery disabled;
  `discover_ollama_models=False`, matching the same isolation
  convention `tests/integration/test_chat_pipeline.py` already uses).
  `runtime_factory`/`app`/`client` fixtures
  (`tests/api/conftest.py`) are **module-scoped**: one full
  `ParikaRuntime` per test file, not per test function, since
  constructing one loads all 14 Modules and ~50 Tools/capabilities —
  sharing it across a file's tests keeps the suite's total thread
  churn low without weakening any test's isolation (each router's
  tests do not depend on execution order beyond what a fresh runtime
  already guarantees, e.g. a Module starting active by default).
- **`tests/api/ws/test_chat_ws.py`** — the streaming chat WebSocket,
  via `TestClient.websocket_connect`.
- **`tests/api/test_error_mapping.py`** — the centralized
  `parika/api/errors.py` suffix-matching table (section 14.2 of the
  now-merged Server Platform design), including that `Router`'s
  `DispatchError` wrapper is correctly unwrapped back to the original
  Core exception for classification.
- **`tests/api/test_router_bindings.py`** — every `Route` registered
  by `register_router_bindings()` actually dispatches through the
  real, unmodified `Router` Core component end to end.
- **`tests/api/test_auth_integration.py`** — `[api.auth].mode`
  actually gates `/api/v1/...` requests end to end (swapping
  `app.state.auth_backend` after startup, since `Configuration` is
  read-only/file-based by design).

**Note on `TestClient(..., raise_server_exceptions=False)`:**
Starlette's `ServerErrorMiddleware` re-raises every exception into the
ASGI caller (for server-side logging) even after a registered
`app.exception_handler(Exception)` has already produced the correct
JSON response; `TestClient`'s own `raise_server_exceptions=True`
default additionally surfaces that re-raise as a test failure. Every
fixture in `tests/api/conftest.py` passes
`raise_server_exceptions=False` so these tests assert on the actual
HTTP response a real deployed server sends, not on this test-harness
artifact.

------------------------------------------------------------------------

# 6. Coverage

To measure coverage, install `coverage` and run:

```bash
uv pip install coverage
coverage run -m pytest
coverage report -m
```

Every implemented Core component, the Web Search Tool, the Web Search
Module, the Chat Module, the Ollama provider, and the Interface layer
(including the CLI) currently have full unit test suites, plus end-to-end
integration coverage for both the Web Search pipeline and the chat/
tool-calling pipeline. New Core components, Modules, Providers, or Tools
should reach the same coverage shape described in section 3 before being
considered complete.

------------------------------------------------------------------------

# 7. Type Checking

`mypy` is used for static type checking (install via
`uv pip install mypy`):

```bash
mypy parika/
```

At the time of writing, running this against the full `parika/` tree
reports two or three pre-existing errors depending on whether
`types-psutil` is installed in the active environment:

- `capability_executor.py` and `knowledge_manager.py` report one error
  each, both inside components that are part of the project's frozen
  architecture and were not modified by this work.
- `resource_manager.py` additionally reports a missing-stubs error for
  `psutil` when `types-psutil` is not installed (`pip install types-psutil`
  resolves it); this is an environment/dependency detail, not a code
  defect.

Every component added by this milestone (`parika/providers/ollama/`,
`parika/modules/chat/`, `parika/interfaces/`, including the CLI) type-checks
cleanly with no new errors.
