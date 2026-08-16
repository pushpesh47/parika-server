# Provider Tool Calling Development Guide

**Audience:** Contributors adding a new Tool-backed capability, adding
a new Provider, or diagnosing a tool-calling issue.

**Status:** Describes the live implementation in
`parika/providers/ollama/`. See
[`Provider_Tool_Calling.md`](../architecture/Provider_Tool_Calling.md)
for the full architectural description and
[`adr/0002-provider-tool-calling-hardening.md`](../architecture/adr/0002-provider-tool-calling-hardening.md)
for why it is built this way.

------------------------------------------------------------------------

## 1. The Golden Rule

**The Provider never knows what a tool does.** It advertises whatever
`OllamaToolSpec`s it is given, parses whatever the model sends back,
and calls `Brain.handle()` with whatever capability id the matching
spec declares. If you find yourself writing `if tool_name == "..."` or
`if capability_id == "..."` anywhere inside `parika/providers/ollama/`,
you are doing it wrong - that decision belongs to the model (which tool
to call) or to whoever builds the tool roster (AI Context Engineering's
`parika/interfaces/ai_context/tool_context.py`, orchestrated by
`chat_capability.py`, which tools to advertise), never to the Provider
driver itself.

## 2. Adding a New Tool-Backed Capability

This requires **zero** Provider changes, and **zero** AI Context
Engineering changes. Follow [`Module_Guide.md`](Module_Guide.md) and
[`Tool_Guide.md`](Tool_Guide.md) exactly as for Web Search or Runtime
Info:

1. Implement a `ToolDriver` and register a `Tool` + `CapabilityDefinition`
   (category `TOOL`) via a Module.
2. If you want a curated Tool Affordance Contract advertised to the
   model (rather than the generic permissive fallback), define it in
   your own Tool's `manifest.py` (see e.g. `parika/tools/weather/
   manifest.py`'s `WEATHER_TOOL_AFFORDANCES`) and pass it as
   `metadata={"tool_affordance": ...}` when registering the
   `CapabilityDefinition` in your Module's driver (see
   `parika/modules/weather/driver.py`). The Tool owns its own
   contract - JSON Schema parameters plus purpose/use-and-avoid/
   requirement/result/failure guidance; AI Context Engineering
   (`ai_context/tool_context.py`) only ever discovers it generically
   from `CapabilityDefinition.metadata` -- it never defines or
   hardcodes any capability's contract itself (Capability
   Independence; see `Request_Understanding.md` §4.4).

That's it. `ai_context.capability_context.discover_capabilities()` and
`ai_context.tool_context.discover_tool_specs()` already pick up every
enabled `TOOL`-category capability automatically; the tool-calling
loop already handles it generically. `discover_capabilities()` now
also runs the read-only Capability Catalog retrieval/ranking pass
(`parika.core.capability_catalog`, see `Request_Understanding.md`
§4.6) -- while the total number of enabled `TOOL`-category
capabilities stays within its budget (the common case), this is a
pure pass-through and every capability is still discovered
automatically exactly as described here. There is no `InferenceRule`/
Requirement Inference step left to add: that framework has been
removed as part of the AI Context Engineering migration (see
[`Request_Understanding.md`](../architecture/Request_Understanding.md)
and [`Requirement_Inference_Guide.md`](Requirement_Inference_Guide.md),
now retitled to describe Capability Discovery) - relevance is decided
entirely by the model's own native tool-calling reasoning, not by a
pattern that must be kept in sync per capability.

## 3. How Tool Calls Are Recognized

Two layers, in order (`driver.py`'s `_chat_once()`):

1. **Native field** (`wire.py::parse_tool_calls()`): Ollama's own
   `message.tool_calls` JSON array. Accepts `arguments` as either a
   JSON object or a JSON-encoded string.
2. **Generic text fallback** (`text_tool_calls.py`): only attempted
   when (a) the native field was empty, (b) at least one tool was
   offered, and (c) the content contains recognizable markup
   (`<tool_call>` or `<function=`). Recognizes markup **shape**, never
   a specific tool name - see `Provider_Tool_Calling.md` §4.1 for the
   two supported shapes.

If you discover a *third* leaked-markup shape from some other model,
add a new `_parse_*_style()` function to `text_tool_calls.py` and call
it from `parse_text_tool_calls()`, following the exact same pattern
(shape-based regex, never a tool-name check). Add the exact reproduced
content as a test case in `test_text_tool_calls.py` - reproducing the
real output (not a hypothetical one) is what made the existing fixes
trustworthy.

## 4. How to Diagnose "the model didn't call my tool"

With `logging.level = "DEBUG"` (see `Running.md` §7), look for this
sequence per turn (`transparency.py`'s helpers, called from
`driver.py`):

```text
Sending request: ... advertised_tools=[...]     <- is your tool actually in this list?
Streaming started (if streaming)
Native tool calls received: ... count=N          <- did Ollama's own field report anything?
[WARNING] Recovered N tool call(s) from leaked... <- did the fallback have to step in?
Tool requested: ... tools=[...]                    <- what did PARIKA end up dispatching?
```

If `advertised_tools` doesn't include your tool: check
`chat_capability.py::discover_tool_specs()` - is your Capability
`enabled` and category `TOOL`?

If `Native tool calls received: count=0` and no `Recovered` warning
follows: the model genuinely chose not to call anything (or its output
didn't match either recognized fallback shape) - this is a model
behavior/prompting question, not a framework bug. Try a different
locally installed model; not every model reliably uses tools.

If you see a `Recovered` warning for a *new* model/shape you haven't
seen before: that confirms the fallback mechanism engaged. If it
*doesn't* recover a call you can see in the raw content, that shape
isn't recognized yet - see §3 above.

## 5. How Empty Final Responses Are Handled

If a turn (final, no tool call) comes back with blank content, you'll
see:

```text
[WARNING] Empty final response from model=...; retrying (1/1) with the same conversation.
```

This is entirely automatic (`chat_loop.py::_chat_once_with_empty_retry()`)
and does not consume any of `max_tool_iterations`'s own budget. If you
see this warning frequently for a particular model, that model may be
unreliable for this milestone's kind of workload; consider excluding
it from Model Selection weighting rather than raising the retry budget
(raising it trades latency for a diminishing chance of recovery).

## 6. Common Mistakes to Avoid

- **Do not** add `if capability_id == "web.search"` (or any other
  specific id) anywhere in `parika/providers/ollama/`. If a capability
  needs special request-building, that belongs in whoever builds the
  `Goal.provider_request_builder` (the Interface layer), not the
  Provider driver.
- **Do not** assume `arguments` is always a `dict` when writing new
  parsing code - some templates emit a JSON string; always go through
  `parse_tool_calls()`'s coercion, never read `function["arguments"]`
  directly.
- **Do not** raise from inside a `ScoringRule` or `InferenceRule` to
  "fix" a Provider-level parsing problem - those frameworks are
  correctly unaware of parsing details; keep the fix at the layer that
  actually failed.
- **Do not** increase `MAX_EMPTY_FINAL_RESPONSE_RETRIES` casually - it
  adds real latency to every affected turn; a genuinely unreliable
  model is better excluded or deprioritized in
  `[model_selection.weights]` than compensated for with more retries.

## 7. Where to Look for Examples

- `tests/providers/ollama/test_text_tool_calls.py` - every recognized
  markup shape, including the exact reproduced `qwen3-coder:latest`
  output.
- `tests/providers/ollama/test_wire.py` - native field parsing,
  including the JSON-string-arguments case.
- `tests/providers/ollama/test_ollama_driver.py::TestEmptyFinalResponseRetry` -
  the empty-response retry's exact budget semantics.
- `tests/integration/test_tool_calling_framework.py` - the complete,
  capability-agnostic, framework-driven validation suite; use this as
  the template for validating any *new* generic Provider behavior (as
  opposed to a specific capability's own tests).
