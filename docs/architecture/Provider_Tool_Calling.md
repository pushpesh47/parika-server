# PARIKA Provider Tool Calling — Lifecycle, Hardening, and Validation

**Status:** Live, implemented, and tested. This document describes what
actually exists in the codebase today, produced by the backend
stabilization milestone that hardened and validated the generic
Provider Tool Calling framework before Web Interface development began.

This document is authoritative for the **generic** Tool Calling
framework - the mechanism by which *any* Tool-backed capability,
present or future, gets invoked by a model via native tool calling. It
does not describe any individual capability (Web Search, Runtime Info,
or any future one); those remain documented in their own Module/Tool
guides.

> **Update (AI Context Engineering migration):** this document was
> written when Requirement Inference (`parika/core/planner/
> requirement_inference/`) still existed. That framework has since
> been completely removed - see
> [`Request_Understanding.md`](Request_Understanding.md). Every
> mention of "Requirement Inference" below (including the captured
> log lines in §8) is a historical record of the investigation as it
> was run at the time; it is not a description of current behavior.
> The generic Tool Calling lifecycle this document validates
> (§3-§7 - native/text-fallback parsing, empty-response hardening,
> the framework-level test suite) is entirely unaffected by that
> removal.

------------------------------------------------------------------------

# 1. Scope of This Milestone

This was explicitly **not** an architecture milestone. No frozen
component's responsibility changed:

- `Brain`, `Planner`, `Requirement Inference`, `ExecutionRequirements`,
  `Model Selection`, `CapabilityRegistry`, `CapabilityResolver`,
  `CapabilityExecutor`, `ToolManager`, `ModuleManager`: **zero
  responsibility changes.** `Planner`'s own orchestration logic in
  `planner.py` was touched exactly once, additively (see §6), and no
  other file in `model_selection/` or `requirement_inference/` needed
  any change at all - both frameworks already worked correctly; the
  reported bottleneck was entirely inside the Provider.
- The fixes are entirely inside `parika/providers/ollama/` (the
  Provider) and `parika/interfaces/` (the CLI's `/reload` command).
- Every fix is **capability-agnostic**: none of them reference a
  specific tool, capability, or Module name. They work identically for
  Web Search, Runtime Info, and any future Tool-backed capability.

------------------------------------------------------------------------

# 2. Root Cause Investigation

The reported symptom - "models return natural language responses
instead of native tool calls; `tool_calls = 0`" - was investigated by
reproducing real requests against every model installed in a live
Ollama instance (`qwen3:8b`, `glm-4.7-flash:latest`,
`qwen3-coder:latest`, `qwen3-coder-next:latest`, `deepseek-r1:14b`),
with the exact wire format PARIKA sends (two tools advertised, the same
system prompt, the same message shape).

**Finding:** the wire format itself was already correct.
`qwen3:8b`, `glm-4.7-flash:latest`, and `qwen3-coder-next:latest` all
correctly populated Ollama's native `message.tool_calls` field for the
identical request. One specific, locally installed model
(`qwen3-coder:latest`) reproducibly emitted its chat template's raw
tool-call markup as **plain text** in `message.content` instead -
specifically when two or more tools were advertised at once - even
though the same model correctly used the native field with only one
tool advertised:

```text
<function=get_current_datetime>
<parameter=timezone>
IST
</parameter>
</function>
</tool_call>
```

Because Model Selection (unmodified, working exactly as designed)
scores this model highly for many everyday requests (favorable
latency/context-window signals), it was frequently selected - making
this model-specific template quirk look like a systemic Provider
defect. It is not: it is a real, observed model/template limitation of
one local build, and the fixes below make the framework **robust to
it**, generically, rather than special-casing that one model.

A second, independent, non-deterministic finding: any model can
occasionally produce a genuinely blank final answer (no tool call, no
content) - most often immediately after a tool result was fed back.
This is inherent to LLM sampling, not a deterministic bug.

------------------------------------------------------------------------

# 3. The Generic Tool Calling Lifecycle

```text
User
  |
  v
Brain -> Planner -> Requirement Inference -> ExecutionRequirements
  -> Model Selection -> Provider
  |
  v
OllamaProviderDriver.chat() -> chat_loop.run_chat_loop()
  |
  |-- _chat_once_with_empty_retry()      (see §5: empty-response hardening)
  |     `-- POST /api/chat
  |
  |-- parse_tool_calls(message.tool_calls)       (native field, see §4.2)
  |-- if empty: parse_text_tool_calls(content)   (generic fallback, see §4.1)
  |
  v
Native Tool Call(s) resolved
  |
  v
ToolCallResolver.resolve() -> Brain.handle() (never bypasses Planner)
  -> Planner -> TaskManager -> CapabilityExecutor -> ToolManager
  -> Tool Driver -> Tool Result
  |
  v
Tool result fed back as a "tool" role message -> loop continues
  |
  v
Provider produces the Final Synthesized Response
```

Every arrow in this diagram was exercised end to end, both with real
capabilities against a live Ollama instance and with synthetic,
capability-agnostic fixtures in
`tests/integration/test_tool_calling_framework.py` (§7).

------------------------------------------------------------------------

# 4. Native Tool Call Parsing (Hardened)

`parika/providers/ollama/wire.py`'s `parse_tool_calls()` and the new
`parika/providers/ollama/text_tool_calls.py` together make tool-call
recognition robust across model/template variation, without ever
naming a specific tool.

## 4.1 Generic Text-Based Fallback (new)

When Ollama's native `message.tool_calls` field is empty but the
model was offered at least one tool, `driver.py` checks whether
`message.content` looks like leaked tool-call template markup
(`text_tool_calls.looks_like_text_tool_call()` - a cheap substring
check so ordinary prose is never touched) and, if so, attempts to
recover it generically:

- **Hermes/ChatML style:** `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`
- **XML style:** `<function=NAME><parameter=KEY>VALUE</parameter></function>`

Both parsers work for *any* function name and *any* argument
names/values - they recognize markup **shapes**, never specific tools.
A recovered call is logged at `WARNING` (a degraded-but-handled
condition worth surfacing) and processed exactly like a natively
reported call from that point on; the leaked text is discarded from
`content` since it was template noise, not an answer.

## 4.2 Native Field Robustness (hardened)

`parse_tool_calls()` now accepts a tool call's `arguments` as either a
JSON object (the common case) or a JSON-encoded **string** of one -
another observed template variation across models - falling back to
an empty dict only when neither shape parses.

------------------------------------------------------------------------

# 5. Empty Final Response Hardening (new)

`chat_loop.py`'s `_chat_once_with_empty_retry()` retries a single
round trip, with the exact same conversation and no other changes, up
to `MAX_EMPTY_FINAL_RESPONSE_RETRIES` (currently `1`) times when a
model produces neither a tool call nor any content. This budget is
**independent of** `max_tool_iterations`: it lives inside a single
round trip, so it never reduces the number of genuine tool-calling
iterations a request is entitled to. If the retried attempt decides to
call a tool instead of answering, that tool call is processed
completely normally by the outer loop.

------------------------------------------------------------------------

# 6. Requirement Inference / Model Selection: No Changes Needed

> This section describes this milestone's own, original scope. A
> later, separate milestone added exactly one small, additive change
> to this lifecycle -- see §13.

Both frameworks already worked correctly and needed **no logic
changes**. Concretely:

- `tool_calling = REQUIRED` (Requirement Inference, unmodified) already
  causes `filtering.py` (Model Selection, unmodified) to exclude any
  model lacking `ModelExecutionFeature.TOOL_CALLING` before scoring
  even runs.
- Once a tool-calling-capable model is selected, whether it *uses* a
  tool is the model's own decision - `Planner` correctly has no
  further role here, and none was added.

The only Planner-adjacent change is purely additive **logging**
(§8): `planner.py`'s `plan()` now also logs planning duration and the
generated plan's steps; this is not a logic change and does not affect
`test_planner.py` (frozen, unmodified, still passing).

------------------------------------------------------------------------

# 7. Framework-Driven Validation

`tests/integration/test_tool_calling_framework.py` validates the
**generic framework**, deliberately using synthetic, generically-named
fixtures (`capability.alpha`/`tool_alpha`, `capability.beta`/`tool_beta`)
registered directly against the real Core stack - never a real,
specific capability - so the suite proves the *framework* works, not
any one Tool. Categories covered, each with the real `Brain`, `Planner`,
`TaskManager`, `CapabilityExecutor`, `ToolManager`, and the real
`OllamaProviderDriver` (only the outermost `OllamaTransport` is faked):

1. **No Tool execution required** - a direct response, and confirming
   advertised tools never *force* a call.
2. **A single Tool-backed capability** - full round trip, including
   JSON-string arguments and the text-based fallback recovery (the
   exact reproduced `qwen3-coder:latest` markup, verbatim).
3. **Multiple Tool-backed capabilities** - two simultaneous calls in
   one turn, and two sequential calls across turns, with tool-result
   ordering verified.
4. **Conversation continuity** - message history shape after a tool
   call turn, and a second, independent chat Goal working correctly
   after a prior turn already executed a tool (no shared-state
   corruption).
5. **Failure scenarios** - tool execution failure, unknown tool name,
   an "invalid" call (missing arguments, dispatched anyway - argument
   validation is each Tool Driver's own responsibility, never the
   framework's), Provider connection failure, Provider timeout,
   exceeding `max_tool_iterations`, and partial multi-tool failure
   (one call succeeds, one fails, both still reported).

This suite is what `Model_Selection_Framework.md` and
`Request_Understanding.md`'s own validation suites deliberately do
not attempt: proving the orchestration mechanism itself is correct,
independent of which capability exercises it.

Capability-specific regression coverage continues to live in
`tests/integration/test_chat_pipeline.py` (Web Search) and
`test_runtime_info_pipeline.py` (Runtime Info), unmodified by this
milestone.

------------------------------------------------------------------------

# 8. Observability

New diagnostics, all DEBUG-level unless noted, added without changing
any component's responsibility:

| Stage | What is logged | Where |
|---|---|---|
| Requirement Inference | Matched rule ids, inferred `tool_calling`/`information_freshness`/`capability_hints` (or the neutral-default reason when nothing matched) | `requirement_inference/resolver.py` |
| Planner | Requirements (now including freshness/hints), planning duration, generated plan steps `(goal_id, capability_id, backend)` | `model_selection/selector.py`, `planner.py` |
| Model Selection | Per-candidate score breakdown, rejection reasons, selected provider/model, selection duration | `model_selection/selector.py` (unchanged from the previous milestone) |
| Provider | Advertised tool **names** (not just a count), native tool call count received, `WARNING` when a call is recovered from leaked text, tool requested, follow-up request after tool execution, `WARNING` on an empty-response retry, execution completed with timing | `transparency.py`, `driver.py` |
| CapabilityExecutor / ToolManager | Capability lifecycle, execution timing, success/failure, tool dispatch (already present and sufficient - unmodified) | `capability_executor.py`, `tool_manager.py` |

Example, captured from a real Ollama instance (a request that
triggered the text-fallback recovery):

```text
DEBUG parika.core.planner.requirement_inference.resolver Requirement inference: matched_rules=['current_datetime'] -> tool_calling=required information_freshness=real_time capability_hints=['current_datetime'] (capability=chat.respond)
DEBUG parika.core.planner.planner Model selection requirements: capability=text_generation reasoning_level=normal tool_calling=required information_freshness=real_time capability_hints=['current_datetime'] streaming_required=True min_context_window=None
DEBUG parika.providers.ollama.driver Sending request: model=qwen3-coder:latest endpoint=/api/chat streaming=True advertised_tools=['get_current_datetime', 'web_search']
DEBUG parika.providers.ollama.driver Native tool calls received: model=qwen3-coder:latest count=0
WARNING parika.providers.ollama.driver Recovered 1 tool call(s) from leaked template markup in model=qwen3-coder:latest's response content instead of the native tool_calls field: ['get_current_datetime']
DEBUG parika.providers.ollama.tool_calling Executing tool: capability=runtime.current_datetime
DEBUG parika.providers.ollama.tool_calling Tool finished: capability=runtime.current_datetime succeeded=True
DEBUG parika.providers.ollama.chat_loop Submitting tool result: tool=get_current_datetime capability=runtime.current_datetime succeeded=True
DEBUG parika.providers.ollama.driver Sending request: model=qwen3-coder:latest endpoint=/api/chat streaming=True advertised_tools=['get_current_datetime', 'web_search']
DEBUG parika.providers.ollama.driver Execution completed: model=qwen3-coder:latest tool_calls=1 total_time_ms=8372.187
```

------------------------------------------------------------------------

# 9. Public API Stability

Reviewed and stabilized for the future Web Interface, with **no
redesign** - every item below already existed; this section documents
its contract explicitly so it can be relied upon.

| Interface | Contract | Stability note |
|---|---|---|
| `BrainRequest` | `goals: tuple[Goal, ...]` | Unchanged. |
| `BrainResponse` | `request_id`, `plan_id`, `results: tuple[GoalResult, ...]`, `planning_failure: Exception \| None`, `.succeeded` | Unchanged. A planning failure (e.g. no available model) produces an *empty* `results` tuple with `planning_failure` set - never an empty-but-"succeeded" response. |
| `GoalResult` | `goal_id`, `task_id`, `status: TaskStatus`, `response: TaskResponse \| None`, `failure: Exception \| None`, `skipped`, `skip_reason` | Unchanged. |
| **Error reporting** | `GoalResult.failure` is always a generic wrapper (`TaskExecutionError`) by design; the specific root cause (e.g. `OllamaToolCallError`, `WebSearchNetworkError`) is reached by walking `.__cause__` (standard Python exception chaining), never by parsing the top-level message string. | **Newly documented, not changed** - this is existing, correct, intentional `TaskManager`/`CapabilityExecutor` behavior. See `test_tool_calling_framework.py::TestFailureScenarios` for the exact chain depth (`TaskExecutionError.__cause__` -> `CapabilityExecutionError.__cause__` -> the Provider/Tool-specific exception). |
| `InterfaceSession.submit_text(text, *, on_token=None) -> ChatTurnResult` | Chat session lifecycle entry point | Unchanged (previous milestone). |
| **Streaming callback** | `on_token: Callable[[str], None]`, invoked synchronously, once per content fragment of the *final* answer only - never for intermediate tool-calling turns' content, and never for leaked tool-call template markup | **Now actually enforced**, not just assumed - see §11.1. Previously, a model leaking markup as streamed content (§2/§4.1) would reach `on_token` in real time before the driver's end-of-stream recovery could strip it; `ToolMarkupStreamFilter` now withholds any such markup live, so this row's contract holds even for the one known model/template quirk that used to violate it. |
| `ChatTurnResult.chat_response.tool_invocations: tuple[OllamaToolInvocation, ...]` | Tool result representation | Unchanged. Now reliably non-empty whenever a tool call was recovered via the text fallback, not just a natively reported one. |
| `ChatTurnResult.succeeded` / `.error_message` | Execution status | Unchanged. |
| Session continuity | `InterfaceSession` accumulates `OllamaMessage` history across turns; a Goal executing a tool call does not corrupt subsequent, independent Goals' state (verified in §7 category 4) | Unchanged; newly verified. |

No public type's shape changed in this milestone. `RequestOptions`,
`ExecutionRequirements`, `Goal`, and every Interface-layer type from
the previous two milestones are untouched.

------------------------------------------------------------------------

# 10. Extensibility (unchanged guarantee)

Every fix in this milestone is Tool/capability-agnostic by
construction:

- The text-based fallback parser recognizes markup **shapes**, not
  tool names - it will recover a malformed call for any future
  Tool-backed capability exactly as it does for `get_current_datetime`
  today.
- The empty-response retry has no notion of tools or capabilities at
  all - it operates purely on whether a turn produced usable output.
- Adding a new Tool-backed capability still means exactly what it
  meant before this milestone: register a Module/Tool (see
  `Model_Guide.md`/`Tool_Guide.md`), add a known `OllamaToolSpec` to
  `chat_capability.py` if you want a curated schema, and optionally add
  an `InferenceRule` (`Requirement_Inference_Guide.md`). **No Provider
  code change is ever required.**

------------------------------------------------------------------------

# 11. Ollama Provider Hardening Milestone (Streaming, Deduplication, Tool-First)

**Status:** Live, implemented, and tested. This section documents a
second, later hardening pass over the same Provider, addressing three
issues observed in real usage plus one deliberately *rejected*
approach - all still entirely inside `parika/providers/ollama/`, with
zero responsibility changes to any frozen Core component.

## 11.1 Streaming Protocol Filter (fixes the §9 streaming contract)

`parika/providers/ollama/stream_filter.py` introduces
`ToolMarkupStreamFilter`, a small, stateful buffer scoped to a single
streamed turn. `driver.py::_chat_once()` wraps `request.on_token`
with it whenever `request.tools` is non-empty (the same gate
`looks_like_text_tool_call()` already uses, so a tool-less chat is
completely unaffected):

- Every incoming raw content fragment is fed to the filter first.
- Ordinary text is released to the real `on_token` immediately - at
  most a handful of characters are ever provisionally withheld, only
  for as long as they could still be the start of a recognized markup
  hint (`<tool_call>`/`<function=`, spanning as many chunks as
  needed - the filter never inspects a single fragment in isolation).
- The moment a hint is confirmed anywhere in the buffered text,
  everything from that point onward, for the rest of the turn, is
  withheld from display entirely. Genuine preamble text *before* the
  markup (e.g. "Sure, let me check that.") still streams normally.
- If a suspected prefix never actually completes into markup by the
  end of the turn (a false alarm), it is released via `flush()`
  instead of being lost.

This is a pure text filter - it has no notion of tool calls,
capabilities, or Brain. The existing, unmodified recovery pipeline
(§4.1: `looks_like_text_tool_call()` / `parse_text_tool_calls()`,
still operating on the *full, unfiltered* accumulated content) and its
`WARNING`-level recovery log are both untouched; this filter only ever
controls what a streaming caller is shown live, in real time, while
the stream is still in flight.

## 11.2 Tool-Calling Turns Never Carry Displayable Content

`driver.py::_chat_once()` now unconditionally clears an assistant
message's `content` whenever `tool_calls` ends up populated - whether
natively reported by Ollama or recovered via §4.1's text fallback -
even if a model happened to also emit accompanying prose in the same
turn. A tool-calling turn was already excluded from
`InterfaceSession`'s persisted history and from the loop's own return
value (§9's `on_token` row); this closes the one remaining gap where
such a turn's leftover `content` could otherwise still reach a
streaming caller as what looks like a second, superseded "response"
for the same user turn.

## 11.3 Repeated Deterministic Tool-Failure Deduplication

`chat_loop.py::run_chat_loop()` now tracks, purely for the lifetime of
one `run_chat_loop()` call, every `(tool name, canonical JSON
arguments)` pair that has already failed. When the model repeats the
*exact* same call again, the cached failure content is fed back
directly - the tool is never re-executed - via
`_deterministic_call_key()`. Any genuinely different argument value
always executes normally, even for the same tool name; only an
identical repeat of an already-failed call is ever short-circuited.
This does not introduce a new termination mechanism: the existing
`max_tool_iterations` budget (§9) still bounds the loop exactly as
before, so a model that keeps repeating the same failing call
regardless still terminates with `OllamaToolCallError` - it simply no
longer burns a real tool execution on every one of those repeats.

## 11.4 Unknown-Tool Recovery Now Names the Available Tools

`tool_calling.py::ToolCallResolver.resolve()`'s existing "unknown
tool" error - returned when a model requests a tool name it was never
actually offered - now also reports every tool name that *is*
currently available, read generically from `tools_by_name` (never a
hardcoded name). This is ordinary tool-calling protocol feedback (the
same `"tool"`-role message shape used for every other tool result),
letting a model that hallucinated a tool name self-correct to a real
one on its very next turn.

## 11.5 Tool-First Behavior: What Was Deliberately *Not* Done

An improvement to "tools are used whenever they are the correct way to
satisfy a request" was explicitly scoped to **never** inject a hidden
system prompt, additional system-role message, or any other
conversation content from inside the Provider - prompting/message
construction is Planner's (and the caller constructing the
conversation's) responsibility, not the Provider's; see
`PARIKA_Core_Component_Blueprint.md`'s Evolution Rules.

Ollama's `/api/chat` wire format (verified directly against
`ollama/ollama`'s own API reference) offers no `tool_choice` or
equivalent forcing field - only `tools` (advertise), `think`, `format`,
`options`, and `stream`. There is therefore no existing Ollama
capability a Provider could use to *force* tool-first behavior without
prompt engineering. §11.4 is the improvement made within that
boundary: it improves the Provider's handling of the tool-calling
*protocol itself* (recovering from a model's own mistake), not the
model's underlying inclination to call a tool in the first place. See
`Running.md`/this document's §10 for how Requirement Inference
(unmodified, Planner-owned) already expresses "a tool is required for
this request" *before* model selection - that remains the correct,
architecturally sound place for any future, stronger tool-first
mechanism to live, should Ollama ever expose one.

## 11.6 Test Coverage

- `tests/providers/ollama/test_stream_filter.py` - `ToolMarkupStreamFilter`
  unit tests: ordinary text, single- and multi-chunk markup, preamble
  handling, false-alarm flush, per-instance isolation.
- `tests/providers/ollama/test_ollama_driver.py::TestStreamedLeakedMarkupSuppression` -
  full driver-level streaming suppression (including a hint split
  across chunks) and confirmation that normal streaming with tools
  available is unaffected.
- `tests/providers/ollama/test_ollama_driver.py::TestDuplicateResponsePrevention` -
  native `tool_calls` with accompanying content is cleared.
- `tests/providers/ollama/test_chat_loop.py` - deterministic repeated
  failure deduplication, differing-arguments non-interference, and
  the existing `max_tool_iterations` budget still terminating the loop.
- `tests/providers/ollama/test_tool_calling.py` - unknown-tool
  recovery reporting the available tool list.
- `tests/interfaces/test_session.py::test_tool_calling_round_trip_appends_exactly_one_assistant_entry` -
  end-to-end confirmation that a tool round trip still produces
  exactly one `HistoryRole.ASSISTANT` entry.

------------------------------------------------------------------------

# 12. Reasoning Markup Suppression (Web Search Reliability Milestone)

**Status:** Live, implemented, and tested. A model occasionally
narrates its own internal reasoning ("I need to search for that...",
"Let me check...") as plain visible text rather than routing it
through Ollama's dedicated `thinking` response field (which this
driver already never forwards to a caller). Some model templates wrap
this narration in a structural `<think>...</think>` or
`<reasoning>...</reasoning>` block - the same *kind* of leaked
chat-template markup §4.1/§11.1 already handle for tool calls, just
denoting reasoning instead.

## 12.1 `reasoning_markup.py` (new)

- `REASONING_MARKUP_HINTS = ("<think>", "<reasoning>")` - structural
  markers only, never a hardcoded natural-language phrase like "I
  need to search" - so this generalizes to any model/topic without an
  ever-growing phrase list, mirroring `text_tool_calls.MARKUP_HINTS`'s
  own "shape, not wording" design.
- `strip_reasoning_markup(content)` - removes any such block from the
  final accumulated `content`, applied unconditionally in
  `driver.py::_chat_once()` (streamed or not, tools offered or not),
  right where `content` is first read from the response.
- `ReasoningMarkupStreamFilter` - a **new**, separate streaming filter
  class, chained *before* `ToolMarkupStreamFilter` in the streaming
  path. It cannot reuse `ToolMarkupStreamFilter` as-is: that filter
  correctly suppresses *everything* for the rest of the turn once
  leaked tool-call markup is confirmed (the remainder really is
  template noise), but a `<think>...</think>` block is finite and
  self-closing - genuine answer text routinely follows it in the very
  same turn - so suppression must *resume* normal live streaming once
  the closing tag is found, which `ReasoningMarkupStreamFilter`
  implements directly.

## 12.2 Wiring (`driver.py`)

`_chat_once()`'s streaming path now chains two independently-scoped
filters per turn: every raw fragment is fed through
`ReasoningMarkupStreamFilter` first (always, regardless of
`request.tools`), then through `ToolMarkupStreamFilter` (only when
`request.tools` is non-empty, exactly as before). This means ordinary
tool-less streaming text is completely unaffected by either filter
unless it actually contains a reasoning block, and leaked tool-call
markup detection (§11.1) is entirely unchanged.

## 12.3 What Remains Out of Scope

Genuine reasoning narrated as ordinary, unmarked prose (no
`<think>`/`<reasoning>` wrapper at all) cannot be generically
distinguished from legitimate conversational preamble text without
either an LLM call (which `requirement_inference/rules.py` and every
filter in this codebase deliberately avoid - see that module's own
docstring) or a hardcoded phrase list (explicitly avoided per this
milestone's own constraints - "prefer generic heuristics"). This is
an intentionally deferred limitation, not a bug: the structural-marker
case this section covers is the one generically, reliably detectable
without either of those trade-offs.

## 12.4 Test Coverage

- `tests/providers/ollama/test_reasoning_markup.py` - `strip_reasoning_markup()`
  unit tests: `<think>`/`<reasoning>` removal, case-insensitivity, an
  unterminated block at end of string, ordinary content unchanged.
- `tests/providers/ollama/test_ollama_driver.py::TestReasoningMarkupSuppression` -
  full driver-level streaming suppression without tools offered at
  all, a block split across multiple chunks, non-streamed final
  content stripped, and ordinary streaming left unaffected.

------------------------------------------------------------------------

# 13. AI-Assisted Model Selection Refinement: the `model_selection_hint` Argument

§6 above ("Requirement Inference / Model Selection: No Changes
Needed") describes this file's original milestone accurately for its
own scope. A later, separate milestone (see
[`Model_Selection_Framework.md`](Model_Selection_Framework.md) §13)
added exactly one small, additive change to this lifecycle:
`ToolCallResolver.resolve()` (`tool_calling.py`) now extracts one
reserved, generic argument, `MODEL_SELECTION_HINT_ARGUMENT`
(`"model_selection_hint"`), out of a tool call's arguments **before**
that Tool ever sees its own arguments
(`_extract_execution_requirements_override()`), and forwards it as the
Goal's own `Goal.metadata["execution_requirements"]` -- the exact,
pre-existing override channel every other explicit requirement already
used (§6).

This is not a new lifecycle stage: it slots into the *existing* step
in §3's lifecycle diagram where a tool call's arguments become a
`Goal`'s `inputs`. It changes nothing about tool-call parsing (§4),
empty-response hardening (§5), the framework-driven validation
guarantees (§7), or observability (§8) - a tool call carrying no
`model_selection_hint` argument (every tool call before this milestone,
and every tool call from a routing model that chooses not to supply
one) is resolved byte-for-byte identically to before.

- Never validated against a specific Tool's own JSON Schema - every
  existing Tool's `parameters` schema already permits additional
  properties (`"additionalProperties": True`, or no
  `additionalProperties` key at all), so this reserved key never
  causes a schema conflict.
- Never a required argument for any Tool - `_extract_execution_
  requirements_override()` degrades to "nothing to override" for a
  missing, non-mapping, or fully-unrecognized hint, exactly like every
  other optional signal in the Model Selection Framework.
- Only actually influences model selection for a two-step Tool driver
  that itself submits a nested, Provider-backed Goal (`VisionToolDriver`,
  `OcrToolDriver`, `StandardCodingAgent`) and forwards `ToolRequest
  .metadata["execution_requirements"]` onto that inner Goal - see
  `Model_Selection_Framework.md` §6.3/§13.3 for the full mechanics and
  `tests/providers/ollama/test_model_selection_hint.py` for the
  extraction's own test coverage.
