
# PARIKA Request Execution Examples

**Status:** Authoritative example-driven guide explaining how PARIKA executes user requests from input to final response.

> This document complements the Architecture Specification and Decision
> Flow. It does not redefine the architecture, and it does not re-derive
> the pipeline diagram or the per-component decision rules --
> [`PARIKA_Decision_Flow.md`](../architecture/PARIKA_Decision_Flow.md)
> is the single authoritative source for both; this document only adds
> concrete, verified walkthroughs (including real captured log output
> and live-Ollama-verified scores) that document is not the place for.

---

# Purpose

This guide explains **how PARIKA thinks** by walking through complete request execution scenarios, each cross-referencing the exact `PARIKA_Decision_Flow.md` section it demonstrates.

For every example you will see:

- User View
- Object Flow
- Decision Points
- Current implementation status

---

# Contents

1. Simple Provider Request
2. Simple Tool Request
3. Interactive CLI Walkthrough: Chat + Native Tool Calling (Ollama)
4. Intelligent Model Selection Example
5. Requirement Inference Example: Current Time vs. a Greeting (historical -- see the update note in that section)
6. Provider Tool Calling Hardening Example

For the pipeline diagram, Planner's six decisions, Tool/Provider
selection, policy/resource evaluation, failure scenarios, retry, and
the EventBus lifecycle-event sequence, see
[`PARIKA_Decision_Flow.md`](../architecture/PARIKA_Decision_Flow.md)
§1-§9 and §13 directly rather than a restated summary here.

---

# 1. Example – Simple Provider Request

User:

> "Who is the President of India?"

## User View

```text
Question
    ↓
Answer
```

## Internal View

```text
Brain
 ↓
Planner
 ↓
CapabilityResolver
 ↓
Provider Selection
 ↓
TaskManager
 ↓
CapabilityExecutor
 ↓
ProviderManager
 ↓
LLM Provider
```

## Object Flow

```text
BrainRequest
 ↓
Goal
 ↓
ExecutionPlan
 ↓
PlanStep
 ↓
CapabilityExecutionRequest
 ↓
ProviderResponse
 ↓
GoalResult
 ↓
BrainResponse
```

Implementation Status: Supported by the current architecture when a Provider is registered. As of this milestone, the Ollama provider (`parika/providers/ollama/`) is registered by default via `build_default_runtime()` and exposes every locally installed Ollama model as a `TEXT_GENERATION` `ProviderModel`, satisfying the `chat.respond` Capability registered by the Chat Module. See section 3 for the concrete CLI walkthrough of this example.

---

# 2. Example – Simple Tool Request

User:

> "Search PARIKA architecture"

```text
Brain
 ↓
Planner
 ↓
CapabilityResolver
(category = TOOL)
 ↓
ToolManager
 ↓
Web Search Tool
 ↓
ToolResponse
 ↓
BrainResponse
```

Reason:

- Capability category is TOOL.
- Planner selects ToolManager.
- ToolManager delegates to the Web Search Tool.

See `PARIKA_Decision_Flow.md` §12 (Example B) for the real, verified,
end-to-end version of this request, including how a second, dependent
Goal could synthesize a cited answer from the raw results (supported by
Planner's dependency ordering today; not yet automatically wired) and
how the Ollama provider's own native tool-calling loop already achieves
an equivalent outcome without it.

**Components not yet wired into the Goal pipeline:** `WorkflowEngine`
(step execution not yet implemented, §17 of
`Core_Component_Responsibilities.md`) and the Core `ContextManager`
component (distinct from Brain's private `context_engine` subpackage,
which is opt-in and live, §29 of the same document) are both complete,
tested Core components with no current caller in the live pipeline.
`MemoryManager`/`KnowledgeManager` are wired, but only into Brain's
optional `assemble_context()` step, not automatically into every Goal;
see `Core_Component_Responsibilities.md` §12/§13/§29 for their current,
verified implementation status.

---

# 3. Interactive CLI Walkthrough: Chat + Native Tool Calling (Ollama)

This example walks through the exact request PARIKA executes when a user
types a question into the `parika` CLI that needs live web information,
end to end, including native Ollama tool calling.

## User View

```text
$ parika
PARIKA v0.1.0
Type /help for commands, or start chatting. Ctrl+D to exit.

> Search the web for the latest PARIKA architecture news
[used tool `web_search` - ok]
Here is a summary of what I found... (cites the search results)
```

## Object Flow

```text
Free text
  |
  v
InterfaceSession.submit_text()
  |
  v
Goal(capability_id="chat.respond",
     provider_request_builder=<builds OllamaChatRequest>)
  |
  v
BrainRequest -> Brain.handle()
  |
  v
Planner.plan()
  |-- CapabilityResolver.resolve("chat.respond") -> category=LLM
  |-- ResourceManager.get_resource_snapshot()
  |-- PolicyEngine.evaluate()                    -> ALLOW
  |-- select_provider_model()                    -> provider.ollama, Model Y
  v
ExecutionPlan[ PlanStep(target=PROVIDER, model=Y) ]
  |
  v
TaskManager.create()+execute() -> CapabilityExecutor.execute()
  |
  v
ProviderManager.execute(provider.ollama, model=Y, OllamaChatRequest)
  |
  v
OllamaProviderDriver.chat()
  |
  |-- POST /api/chat -> model responds with tool_calls=[web_search(query=...)]
  |
  |-- Driver resolves the call through Brain (NOT ToolManager directly):
  |     Goal(capability_id="web.search", inputs={"query": ...})
  |     -> Brain.handle() -> Planner -> TaskManager -> CapabilityExecutor
  |        -> ToolManager -> WebSearchToolDriver -> Internet
  |     -> ToolResponse fed back as a "tool" role chat message
  |
  |-- POST /api/chat again (with the tool result in the conversation)
  |     -> model responds with a final answer, no further tool_calls
  v
OllamaChatResponse(message=<final answer>,
                    tool_invocations=(<web_search invocation>,))
  |
  v
(flows back up unopened through CapabilityExecutionResponse ->
 TaskResponse.outputs["result"] -> GoalResult.response -> BrainResponse)
  |
  v
ChatTurnResult -> format_chat_turn() -> CLI Markdown renderer -> terminal
```

## Decision Points

- **Tool or Provider?** `chat.respond` resolves to category `LLM`, so
  Planner always routes to `_select_provider_model()`, never
  `_select_tool()` — exactly as in section 1.
- **Which capability, module, tool selected for the actual web search?**
  `web.search` (category `TOOL`), owned by the Web Search Module, executed
  by the Web Search Tool — exactly as in section 2. The *decision* to call
  it is made by the Ollama model itself via tool calling, not by PARIKA.
- **Does PARIKA ever bypass Planner for the tool call?** No. `OllamaProviderDriver`
  only ever calls `Brain.handle()`, which always goes through Planner,
  CapabilityResolver, PolicyEngine, and ToolManager exactly like any other
  Goal (see `PARIKA_Decision_Flow.md` section 4.4 and `Running.md` section
  8.3).

## Why Each Core Component Participates

Identical to sections 1 and 2 above, with the Chat Module in the role
Web Search plays in section 2, and the Ollama provider in the role of
"an LLM Provider" in section 1. Nothing about Brain, Planner, TaskManager,
CapabilityExecutor, ToolManager, or ProviderManager changed to support
this — the Interface layer and the Ollama provider are additive.

## Current Implementation Status

Live and tested: `tests/integration/test_chat_pipeline.py`,
`tests/providers/ollama/test_ollama_driver.py::TestChatToolCalling`, and
verified against a real, locally running Ollama instance and the real
internet through the `parika` CLI (see `Running.md` sections 8.3 and 8.5).

---

# 4. Intelligent Model Selection Example

This example shows the extra step Planner now performs before the
Provider Selection described in `PARIKA_Decision_Flow.md` §4.4: instead
of picking the first capability-matching model, it scores every
candidate and logs the full decision. See
[`Model_Selection_Framework.md`](../architecture/Model_Selection_Framework.md)
for the complete design.

## Setup

Three Ollama models are installed and discovered:

| Model | Reports as reasoning-capable | `estimated_latency_ms` | `context_window` |
|---|---|---|---|
| `deepseek-r1:14b` | yes | 3752 | 131072 |
| `qwen3-coder:latest` | no | 2030 | 262144 |
| `qwen3:8b` | yes | 2168 | 40960 |

A user sends a plain greeting through the CLI. `chat.respond` resolves to
category `LLM`; the CLI's `provider_request_builder` did not attach any
special hints, so `ExecutionRequirements` gets the category default:
`reasoning_level=NORMAL`, `tool_calling=PREFERRED` (a Tool capability -
`web.search` - is available to advertise).

## What Planner Logs

```text
DEBUG Model selection requirements: capability=text_generation reasoning_level=normal tool_calling=preferred streaming_required=False min_context_window=None
DEBUG Candidate provider=provider.ollama model=deepseek-r1:14b score=81.19 breakdown=[latency=27.12, reasoning=20.00, tool_calling=20.00, context_window=4.07, cost=5.00, prefer_local=5.00, prefer_streaming=0.00, prefer_healthier_provider=0.00]
DEBUG Candidate provider=provider.ollama model=qwen3-coder:latest score=105.00 breakdown=[latency=40.00, reasoning=25.00, tool_calling=20.00, context_window=10.00, cost=5.00, prefer_local=5.00, prefer_streaming=0.00, prefer_healthier_provider=0.00]
DEBUG Candidate provider=provider.ollama model=qwen3:8b score=88.97 breakdown=[latency=38.97, reasoning=20.00, tool_calling=20.00, context_window=0.00, cost=5.00, prefer_local=5.00, prefer_streaming=0.00, prefer_healthier_provider=0.00]
DEBUG Selected provider=provider.ollama model=qwen3-coder:latest score=105.00 thinking_mode=auto reasoning_enabled=None selection_time_ms=0.30
```

## Why `qwen3-coder:latest` Won

- **`reasoning=25.00` vs `20.00`:** `ReasoningRule` mildly disfavors
  reasoning-capable models (`deepseek-r1:14b`, `qwen3:8b`) for a
  `NORMAL` request - the direct fix for "reasoning models used
  unnecessarily."
- **`latency=40.00` (the maximum possible):** `qwen3-coder:latest` has
  the lowest `estimated_latency_ms` of the three, and
  `latency_estimation.py` scales that estimate up for reasoning-capable
  models specifically, based on Ollama's own reported capability - not
  a hardcoded model name.
- **`context_window=10.00` (the maximum possible):** it also happens to
  report the largest context window of the three.

None of `deepseek-r1:14b`'s or `qwen3:8b`'s scores are zero: both remain
entirely usable candidates, and either would still win instead if
`qwen3-coder:latest` were unavailable, or if the request's
`reasoning_level` were `COMPLEX`.

## Decision Points

- **Where is this decided?** Exclusively inside Planner
  (`model_selection.select_provider_model()`), reading
  `ProviderManager.get_all()`. `ProviderManager` itself never scores or
  chooses anything - see `Model_Selection_Framework.md` §2.
- **Where do the weights (`40`/`25`/`20`/`10`/`5`) come from?**
  `config/defaults.toml`'s `[model_selection.weights]`, read through the
  Core `Configuration` component. Changing them requires no code change.
- **Where does `estimated_latency_ms` come from?** Ollama's own
  `/api/tags`/`/api/show` `parameter_size`, scaled by whether Ollama
  itself reports the model as reasoning-capable
  (`parika/providers/ollama/latency_estimation.py`) - never a hardcoded
  number tied to a specific model name.

## Current Implementation Status

Live and tested:
`tests/core/planner/model_selection/`,
`tests/core/planner/test_planner_model_selection.py`, and verified
against a real, locally running Ollama instance (the exact scores above
were captured from a live run).

---

# 5. Requirement Inference Example: Current Time vs. a Greeting (historical)

> **Update (AI Context Engineering migration):** Requirement Inference
> (`parika/core/planner/requirement_inference/`), described throughout
> this section, has since been completely removed - see
> [`Request_Understanding.md`](../architecture/Request_Understanding.md)
> for the current design. This section is kept as a historical record
> of the live-captured example (logs and final answer below); the
> `tool_calling=REQUIRED` signal for a `get_current_datetime` turn now
> comes from `chat_capability.build_chat_goal()`'s structural
> `tool_calling="preferred"` override (set whenever a non-empty tool
> roster is offered) rather than from message-text pattern matching,
> and a request no longer needs the message to look like a
> date/time question specifically to receive that signal.

Shows the extra step Planner previously performed *before* section 4's
model selection: deriving `tool_calling`/`information_freshness` from
the message itself, rather than every request defaulting to the same
value.

## Two Requests, Two Different Requirements

```text
User: "Hello there!"
  -> Goal.inputs = {"message": "Hello there!"}
  -> Requirement Inference: GreetingRule matches
  -> ExecutionRequirements(tool_calling=NOT_NEEDED, information_freshness=STATIC)
  -> Model Selection picks the fastest available model; no tool-calling
     requirement filters anything out

User: "What is the current time in IST?"
  -> Goal.inputs = {"message": "What is the current time in IST?"}
  -> Requirement Inference: CurrentDateTimeRule matches
  -> ExecutionRequirements(tool_calling=REQUIRED,
                            information_freshness=REAL_TIME,
                            capability_hints={CURRENT_DATETIME})
  -> Model Selection excludes any model lacking
     ModelExecutionFeature.TOOL_CALLING *before* scoring runs
  -> Selected model calls get_current_datetime(timezone="IST")
  -> Runtime Info Tool reads the real system clock
  -> Final answer uses the real date/time, not a guess
```

## What Actually Runs (verified live)

```text
DEBUG Model selection requirements: capability=text_generation reasoning_level=normal tool_calling=required streaming_required=False min_context_window=None
...
DEBUG Selected provider=provider.ollama model=qwen3:8b ...
DEBUG Sending request: model=qwen3:8b endpoint=/api/chat streaming=False tools=2
DEBUG Tool requested: model=qwen3:8b tools=['get_current_datetime']
DEBUG Executing tool: capability=runtime.current_datetime
DEBUG Tool finished: capability=runtime.current_datetime succeeded=True
DEBUG Submitting tool result: tool=get_current_datetime capability=runtime.current_datetime succeeded=True
DEBUG Execution completed: model=qwen3:8b tool_calls=1 total_time_ms=22283.294
```

Final answer (real output): *"The current time in IST (Indian Standard
Time) is Wednesday, 29 July 2026, 11:54:31. This corresponds to a UTC
offset of +05:30."*

## Decision Points (at the time this example was captured)

- **Where was "does this need a tool" decided?** Inside Planner
  (`requirement_inference.infer_requirement_hints()`), reading only
  `Goal.inputs["message"]` via deterministic pattern matching. This
  mechanism has since been removed; see the update note above for the
  current mechanism.
- **Where is "which tool gets called" decided?** By the model itself,
  during its own native tool-calling loop
  (`OllamaProviderDriver`/`chat_loop.py`, unchanged) - unaffected by
  the Requirement Inference removal.
- **Does this create a second Goal?** No. Both requests are a single
  `chat.respond` Goal from start to finish - see
  `Request_Understanding.md` section 3 for why automatic multi-Goal
  chaining is explicitly out of scope.

## Current Implementation Status

The Requirement Inference code paths this section documents
(`tests/core/planner/requirement_inference/`,
`tests/core/planner/test_planner_requirement_inference.py`) have been
removed. `tests/integration/test_runtime_info_pipeline.py` still
passes with the current AI Context Engineering design (see
`Request_Understanding.md`).

---

# 6. Provider Tool Calling Hardening Example

Shows the generic recovery mechanisms added by the backend
stabilization milestone, using the exact malformed output reproduced
from a real Ollama server. See
[`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md)
for the complete design.

## Before the Fix (reproduced via direct API call, `qwen3-coder:latest`, two tools advertised)

```json
{"message": {"role": "assistant", "content":
  "<function=get_current_datetime>\n<parameter=timezone>\nIST\n</parameter>\n</function>\n</tool_call>"
}, "done": true}
```

Ollama's native `tool_calls` field was empty - the model's own chat
template leaked its tool-call markup into plain text instead. Before
this milestone, this produced `tool_calls = 0` and PARIKA had nothing
to execute.

## After the Fix (same request, through the real driver)

```text
DEBUG parika.providers.ollama.driver Native tool calls received: model=qwen3-coder:latest count=0
WARNING parika.providers.ollama.driver Recovered 1 tool call(s) from leaked template markup in model=qwen3-coder:latest's response content instead of the native tool_calls field: ['get_current_datetime']
DEBUG parika.providers.ollama.tool_calling Executing tool: capability=runtime.current_datetime
DEBUG parika.providers.ollama.tool_calling Tool finished: capability=runtime.current_datetime succeeded=True
```

Final answer (real output): *"The current time in IST (Indian Standard
Time) is 13:32:09 on Wednesday, July 29, 2026."*

`text_tool_calls.parse_text_tool_calls()` recognized the leaked
`<function=NAME><parameter=KEY>VALUE</parameter></function>` markup
**shape** - not the specific name `get_current_datetime` - so the exact
same code path recovers a leaked call for any current or future
Tool-backed capability.

## A Second Hardening: Empty Final Response Retry

Separately observed in a live, multi-turn CLI session: a model produced
a completely blank final answer immediately after a tool result was fed
back (non-deterministic sampling, not a deterministic bug). On the next
identical run, the same request completed correctly. This class of
failure is now retried automatically:

```text
WARNING parika.providers.ollama.chat_loop Empty final response from model=...; retrying (1/1) with the same conversation.
```

## Decision Points

- **Where does recovery happen?** Exclusively inside the Ollama
  Provider (`text_tool_calls.py`, `chat_loop.py`) - never in Planner or
  Model Selection, neither of which needed any change for this
  milestone.
- **Is this capability-specific?** No. Neither fix ever names a tool,
  capability, or Module - see `Provider_Tool_Calling.md` section 10.

## Current Implementation Status

Live and tested: `tests/providers/ollama/test_text_tool_calls.py`,
`tests/providers/ollama/test_wire.py`,
`tests/providers/ollama/test_ollama_driver.py::TestEmptyFinalResponseRetry`,
`tests/integration/test_tool_calling_framework.py`, and verified against
a real, locally running Ollama instance (the exact malformed content and
final answers above were captured from live runs).

---

# Notes

This document is intentionally example-driven. It should be read together with:

- PARIKA_Architecture_Specification_v1.0.md
- PARIKA_Decision_Flow.md
- Core_Component_Responsibilities.md
- Running.md

A future revision can expand each example with sequence diagrams, timing diagrams, object lifecycles, and complete worked scenarios.
