
# PARIKA Tool Guide

**Status:** Authoritative guide for developing PARIKA Tools.

> This document replaces **Tools.md** and **Tool_Development_Guide.md**.

---

# 1. Purpose

**When to read this:** use this guide when implementing a deterministic tool or extending an existing one.

**Related documents:** [../architecture/PARIKA_Architecture_Specification_v1.0.md](../architecture/PARIKA_Architecture_Specification_v1.0.md), [Module_Guide.md](Module_Guide.md), and [Capability_Guide.md](Capability_Guide.md).

A Tool implements deterministic, non-AI executable logic for one or more Capabilities.

This guide covers:

- Tool architecture
- Tool descriptor
- ToolDriver
- Registration
- Execution
- Request/Response
- Error handling
- Retry
- Logging
- Testing
- Packaging
- Best practices

System-wide architecture is documented elsewhere and is intentionally not repeated.

---

# 2. Architecture

A Tool:

- implements one or more Capabilities
- is registered with ToolManager
- executes only through ToolManager
- delegates execution to a ToolDriver

A Tool never:

- selects itself
- modifies Core
- manages Providers
- manages Workflows
- performs scheduling

Planner selects a Tool.

CapabilityExecutor invokes ToolManager.

ToolManager invokes ToolDriver.

---

# 3. Tool Lifecycle

A Tool has only two runtime states:

```text
Not Registered
      ↓
register()
      ↓
Registered
      ↓
execute()
      ↓
unregister()
      ↓
Not Registered
```

Normally registration is performed by the owning Module.

---

# 4. Tool Descriptor

A Tool contains immutable metadata:

- id
- name
- version
- description
- capabilities
- enabled
- metadata

Create Tool instances through a small factory in `manifest.py`.

---

# 5. ToolDriver

ToolDriver owns execution.

Responsibilities:

- validate input
- execute business logic
- return ToolResponse
- raise domain exceptions

Use dependency injection.

Never create global services inside the driver.

---

# 6. Registration

Registration normally occurs during Module startup.

Registration should:

- register Tool
- associate ToolDriver
- avoid duplicate ids

Unregistration should happen during Module shutdown.

---

# 7. Execution

Execution flow (the Tool-specific slice of
[`../architecture/PARIKA_Decision_Flow.md`](../architecture/PARIKA_Decision_Flow.md)
§7-§8, once Planner has already selected this Tool):

```text
CapabilityExecutor
        ↓
ToolManager.execute()
        ↓
ToolDriver.execute()
        ↓
ToolResponse
```

No component calls ToolDriver directly.

---

# 8. ToolRequest

ToolRequest contains:

- arguments
- parameters
- metadata

Design arguments to match the capability input.

---

# 9. ToolResponse

ToolResponse contains:

- result
- attributes

Return JSON-serializable results whenever possible.

---

# 10. Error Handling

- Create a single ToolError base exception.
- Raise meaningful domain exceptions.
- Let ToolManager wrap execution failures.
- Do not swallow exceptions.

---

# 11. Retry

Retry belongs inside Tool implementations.

Use:

- configurable attempts
- configurable delay
- retry only transient failures
- injectable sleep for testing

---

# 12. Logging

- Inject Logger
- Never use print()
- Log useful diagnostic information only

---

# 13. Testing

Every Tool should test:

- successful execution
- invalid input
- error handling
- retry behavior
- timeout behavior
- external I/O using fake implementations

---

# 14. Packaging

Each Tool is a package:

```text
parika/tools/<tool_id>/
├── __init__.py
├── manifest.py
├── driver.py
└── ...
```

Register Tools from Modules rather than during import.

---

# 15. Best Practices

- Keep drivers small.
- Separate business logic.
- Use dependency injection.
- Keep responses immutable.
- Make external I/O testable.
- Return structured results.

---

# 16. Common Mistakes

- Registering duplicate ids.
- Returning invalid ToolResponse objects.
- Performing heavy work in constructors.
- Directly invoking ToolDrivers.
- Using global state.
- Ignoring cleanup.

---

# 17. Reference Implementation

The Web Search Tool is the canonical reference implementation for all future Tools.

---

# 18. Web Search Provider Failover

The Web Search Tool's `search()` call is served by a `SearchBackend`
built by `parika.tools.web_search.provider_registry.build_search_backend()`
- either a single provider's backend directly, or (when two or more
providers are configured/available)
`search_backend_failover.FailoverSearchBackend`, which tries an
ordered list of providers, falling over to the next one whenever the
current one errors, times out, is served an anti-bot/CAPTCHA
challenge, returns an HTTP error, or returns a malformed response,
until one succeeds or every configured, available provider has failed
(`WebSearchAllProvidersFailedError`).

## 18.1 Backend Naming Convention

Every provider backend lives in its own module named:

```text
search_backend_<provider>.py
```

so every provider stays grouped together alphabetically in a
directory listing, and adding a new one never requires touching an
existing provider's file. Non-provider shared code (the `SearchBackend`
protocol, the registry, common HTML-fetch/retry/validation helpers)
deliberately does **not** follow this pattern, so it is never
mistaken for a provider itself:

| Module | Role |
|---|---|
| `protocol.py` | The `SearchBackend` protocol every provider implements. |
| `backend_support.py` | Shared, provider-agnostic helpers: query validation, retrying an HTTP fetch, and recognizing an anti-bot/CAPTCHA/HTTP-error response - used by every HTML-scraping provider so these concerns are implemented exactly once. |
| `provider_registry.py` | The single place responsible for creating every provider instance (see §18.4). |
| `search_backend_failover.py` | `FailoverSearchBackend` - the provider-agnostic, ordered-try-until-success mechanism itself. |

## 18.2 Supported Providers

| Name (used in configuration) | Module | Requires configuration? |
|---|---|---|
| `google` | `search_backend_google.py` | No |
| `bing` | `search_backend_bing.py` | No |
| `duckduckgo` | `search_backend_duckduckgo.py` | No |
| `mojeek` | `search_backend_mojeek.py` | No |
| `qwant` | `search_backend_qwant.py` | No (uses Qwant Lite's server-rendered HTML) |
| `google_cse` | `search_backend_google_cse.py` | Yes - `[web_search.google_cse]` (API key + Search Engine ID) |

`google`, `bing`, `duckduckgo`, `mojeek`, and `qwant` scrape each
provider's public HTML results page using only the Python standard
library (`html.parser`), exactly like the original
`DuckDuckGoHtmlSearchBackend`. `google_cse` is the one deliberate
exception that requires (and is the only provider PARIKA implements
that requires) a mandatory API key: it calls Google's own official,
JSON-based Custom Search API rather than scraping HTML, so it is not
subject to the CAPTCHA/anti-bot concerns the HTML-scraping providers
document.

## 18.3 Configuration

`config/defaults.toml`'s `[web_search]` section controls provider
selection:

```toml
[web_search]
enabled = true
default_provider = "google"
provider_order = [
    "google",
    "bing",
    "duckduckgo",
    "mojeek",
    "qwant",
    "google_cse",
]

[web_search.google_cse]
api_key = ""
search_engine_id = ""
```

- `enabled`: when `false`, the Web Search Module registers neither its
  Capability nor its Tool at all (mirroring `[providers.ollama].enabled`).
- `default_provider`: tried first. Google is the default - not
  DuckDuckGo - because it consistently produces the highest-quality,
  most broadly relevant results of every no-API-key provider PARIKA
  implements; DuckDuckGo remains a configured failover option, since
  it frequently encounters anti-bot protection.
- `provider_order`: every other configured provider, tried in this
  order after `default_provider` (which need not be repeated in this
  list). Ordered for AI-quality search results, not popularity.
- Only providers that require additional configuration get their own
  `[web_search.<provider>]` section - today, only `google_cse`
  (`api_key`, `search_engine_id`). `google`, `bing`, `duckduckgo`,
  `mojeek`, and `qwant` need no section of their own.

Read by `parika.tools.web_search.config.load_web_search_config()`,
following the same `Configuration.get()`-wrapping pattern as
`parika/core/planner/model_selection/config.py`. When only one
provider ends up configured/recognized/available, `build_search_backend()`
returns that provider's own `SearchBackend` directly (unwrapped), so
its exceptions propagate exactly as they always have for callers that
never configure more than one provider.

## 18.4 Provider Registry and Availability

`provider_registry.py` is the single place responsible for creating
every provider instance - no other module ever instantiates a
`search_backend_<provider>.py` class directly (aside from tests and
`WebSearchModuleDriver`'s explicit `search_backend` override, which
bypasses provider selection entirely by design). Each entry is a
`ProviderRegistration(name, factory, is_available)`:

- `factory(transport, config, tuning) -> SearchBackend` builds the
  provider's backend.
- `is_available(config) -> bool` reports whether the provider is
  currently usable - defaulting to always `True` for every
  no-configuration provider. `google_cse`'s `is_available` checks that
  both `api_key` and `search_engine_id` are non-empty; without either,
  it is skipped entirely, before ever being constructed, so a request
  that is guaranteed to fail (HTTP 400/403) is never attempted.

`build_search_backend()` walks `config.failover_order()`, skips any
name that is unrecognized *or* recognized-but-unavailable (logging
each skip), and either returns the one remaining available provider's
backend directly or wraps every available provider in a
`FailoverSearchBackend`.

### Adding a Future Provider

1. Implement the `SearchBackend` protocol (`protocol.py`) in a new
   module named `search_backend_<provider>.py` (§18.1) under
   `parika/tools/web_search/`.
2. Register one `ProviderRegistration` for it in
   `provider_registry.PROVIDER_REGISTRY`, keyed by the name operators
   will use in configuration. Supply `is_available` if the provider
   needs configuration to function.
3. Add that name to `[web_search].provider_order` (and optionally set
   it as `[web_search].default_provider`) in `config/defaults.toml` or
   any higher-precedence configuration layer. If the provider needs
   its own configuration, add a `[web_search.<provider>]` section and
   read it in `config.py`'s `WebSearchProviderConfig`/
   `load_web_search_config()`.

No other code needs to change - not `WebSearchToolDriver`, not the
`web.search` Capability, not any caller of the Web Search Tool, and
not `FailoverSearchBackend` itself (which has no knowledge of any
specific provider).

## 18.5 Backward Compatibility

`WebSearchModuleDriver`'s `search_backend` constructor parameter still
takes priority over any configuration: when supplied explicitly (as
every existing test that injects a fake backend does), configuration
is not consulted for backend selection at all. A `WebSearchModuleDriver`
constructed with neither `search_backend` nor `configuration` still
defaults to a single provider's backend, unwrapped (`config.py`'s
built-in, single-provider fallback default - see
`DEFAULT_PROVIDER_ORDER`'s docstring) - identical in shape to before
this feature existed, just against the new default provider, Google.

---

# 19. Result Fields: `title`, `url`, `snippet`, `display_url`

`SearchResult` (`search_result.py`) exposes `title`, `url`, `snippet`,
and `display_url` as **separate** fields - never concatenated into
one string. `url` is always the real destination, never a search
provider's own redirect/tracking wrapper: each
`search_backend_<provider>.py` decodes any such redirect whenever
possible (`search_backend_bing.py::_decode_bing_redirect()` decodes
Bing's `bing.com/ck/a?...&u=<encoded>` click-tracking wrapper;
`search_backend_google.py::_unwrap_google_redirect()` decodes Google's
`/url?q=<url>` wrapper). `display_url` carries a provider's
breadcrumb-style rendering of the URL (e.g. `example.com > topic >
page`) *only* when the provider exposes one distinctly from the title
and the real URL - `None` otherwise, which every existing caller
reading only `title`/`url`/`snippet` is entirely unaffected by.

Because Bing's title is specifically the anchor inside a result's
`<h2>` - never a leading site-name/breadcrumb row rendered before it -
`search_backend_bing.py` scopes title-anchor detection to inside an
`<h2>`, rather than "the first anchor with an http(s) href", which
previously produced garbled titles by capturing that leading
breadcrumb row instead (e.g. `"ndtv.comhttps://www.ndtv.com › latest"`
instead of `"Latest News - NDTV"`).

## 19.1 Resilient Parsing Without Depending on Specific Class Names

Google renames the CSS classes wrapping its results frequently enough
that a parser anchored to any specific class name eventually parses
zero results the moment Google ships a markup change, without any
actual loss of the underlying data. `search_backend_google.py`'s
`_GoogleResultParser` instead relies on the one structural fact that
has remained true across every observed Google layout variant: a
result's title is always an `<h3>` immediately preceded by, or
wrapped by, the `<a href="...">` that links to it. Tracking "the most
recently opened anchor with a real destination href" and pairing it
with the next `<h3>` is therefore resilient to markup churn in a way
matching any specific container class (`g`, `MjjYud`, `yuRUbf`,
`zReHs`, ...) is not - while still preferring known snippet class
names as a fast, precise first choice, and falling back to
opportunistically collected plain text otherwise.

---

# 20. Result Selection, Deduplication, and Ranking

`WebSearchToolDriver.execute()` (`driver.py`) is a clean, four-stage
pipeline, each stage an independent, swappable component:

1. **Provider** (the configured `SearchBackend`) fetches and parses a
   *candidate pool* of raw results - deliberately larger than what
   the caller actually asked for (`[web_search].candidate_pool_size`,
   default 20), so a relevant result reported near the end of a
   provider's own order is never discarded before ranking ever sees
   it.
2. **Deduplication** (`dedup.py::deduplicate_results()`) removes
   exact-URL duplicates (after normalizing scheme, `www.`, trailing
   slash, and stripping tracking query parameters like `utm_*`) and
   same-domain near-duplicate titles (via stdlib `difflib`), so a
   repeated result never occupies a slot ranking or truncation would
   otherwise have given to a distinct one. A full kill switch
   (`[web_search].dedup_enabled = false`) disables this stage.
3. **Ranking** (`ranking.py::rank_results()`) scores and reorders the
   deduplicated pool by relevance to the query - a small, generic,
   provider- and topic-agnostic term-overlap heuristic (title-weighted
   higher than snippet, with a small position-based tiebreaker
   favoring the provider's own order for otherwise-equal results). A
   full kill switch (`[web_search].ranking_enabled = false`) restores
   the raw provider order.
4. **Result Selection** (the driver's own final slice) truncates the
   ranked pool down to the caller's actually requested count
   (`[web_search].default_max_results`, default 10, or an explicit
   `max_results` tool-call argument).

This directly fixes two real observed failure modes: a parser could
successfully extract 10 results, but the Tool would only ever return
the first 5 - discarding a relevant result that happened to appear at
rank 10 (fixed by requesting a larger candidate pool and ranking
before truncating); and the pipeline previously had no deduplication
step at all, so a provider reporting the same URL twice (with or
without cosmetically different tracking parameters) could occupy two
of the caller's requested result slots.

Every stage's tunables are configurable
(`[web_search].candidate_pool_size`, `default_max_results`,
`dedup_enabled`, `dedup_title_similarity_threshold`,
`ranking_enabled`, `ranking_title_weight`, `ranking_snippet_weight`,
`ranking_position_decay` - see `config/defaults.toml`), never
hardcoded, following the same `Configuration`-wrapping pattern as
provider selection (§18.3).

---

# 21. Multi-Capability Tool Domains: One Tool per Capability

`ToolRequest` (`parika/core/tool_manager/request.py`) carries only
`arguments`, `parameters`, and `metadata` - no capability identifier.
Planner's `_select_tool()` resolves a Tool purely by `goal.capability_id
in tool.capabilities`, so once a Tool is selected, its `ToolDriver`
has no way to tell *which* capability a request targeted if that one
Tool implements more than one.

Both original Tools (`runtime_info`, `web_search`) sidestepped this
by implementing exactly one Capability each. The Filesystem, Weather,
Currency, and News Tools each implement several Capabilities
(`filesystem.read`/`.write`/.../`.watch`; `weather.current`/
`.forecast`; `currency.exchange_rate`/`.convert`;
`news.latest`/`.search`/`.topic`), and all follow the same pattern to
stay compatible with this constraint: **register one Tool per
Capability**, each with its own `tool.<domain>_<operation>`
identifier and its own `ToolDriver` *instance* bound to that one
operation at construction time (see
`parika/tools/filesystem/manifest.py::FilesystemOperationSpec` and
`FilesystemToolDriver.__init__(operation, ...)` for the fullest
worked example; `weather`/`currency`/`news` use the same shape with a
small `StrEnum` mode instead of a data table, since they have only
2-3 operations each).

This requires **zero Core changes**: `ToolManager`, `CapabilityResolver`,
and `CapabilityExecutor` are all completely unaware that several
registered Tools happen to share one driver *class* (parametrized
differently per instance) - to them, each is just another
single-capability Tool, selected exactly the same way `web.search` or
`runtime.current_datetime` always have been.

When designing a new multi-capability Tool domain, follow this
pattern rather than inventing an `"operation"` argument inside a
single Tool's `ToolRequest.arguments` to dispatch internally - that
would require the caller (or the model, via its tool-call arguments)
to redundantly specify the operation on top of already having chosen
which Capability's tool spec to call, and gains nothing Planner's
existing `capability_id`-based selection does not already provide for
free.

**News Tool dependency note:** `parika/tools/news/feed_reader.py` parses
RSS/Atom feeds using `feedparser`, which is a **required** base
dependency (`pyproject.toml`'s top-level `dependencies`), not an
optional extra - the original Tools Expansion plan for this Tool
proposed it as optional, but every feed source PARIKA ships needed it
unconditionally.

---

# 22. Shell Tool

**Status note:** this section and §23 describe the System Interaction
Foundation (Shell Tool, Filesystem Tool workspace access model,
Workspace Permission Manager) - implemented, tested
(`tests/tools/shell/`, `tests/modules/shell/`,
`tests/integration/test_workspace_permission_pipeline.py`), and wired
into `build_default_runtime()`. `[shell].enabled` is `false` by
default (see §22.6); the Shell Module registers nothing until an
operator opts in. See
`docs/architecture/Core_Component_Responsibilities.md` §25 for the
Workspace Permission Manager itself and
`docs/architecture/PARIKA_Decision_Flow.md` §14 for the end-to-end
decision flow.

The Shell Tool executes OS commands. It follows exactly the "one Tool
per Capability" shape §21 already establishes - the Filesystem Tool is
its direct template - so it requires no change to `ToolManager`,
`Planner`, `CapabilityResolver`, or `CapabilityExecutor`.

## 22.1 Operations

| Operation | Capability id | Tool id | Purpose |
|---|---|---|---|
| `EXECUTE` | `shell.execute` | `tool.shell_execute` | Runs a command to completion, capturing stdout/stderr/exit code, subject to a timeout. |
| `BACKGROUND` | `shell.background` | `tool.shell_background` | Starts a command detached; returns a `process_id` immediately. |
| `PROCESSES` | `shell.processes` | `tool.shell_processes` | Lists/inspects tracked background processes and their captured output. |
| `KILL` | `shell.kill` | `tool.shell_kill` | Terminates a tracked background process. |

`category=CapabilityCategory.TOOL`, `tags={"shell", "system"}` - the
same convention the Filesystem Module already uses (`category=TOOL`
for every deterministic Tool; domain/system-ness is a `tags` entry, not
the `category`).

A single `ShellToolDriver` class is bound to exactly one operation at
construction, exactly like `FilesystemToolDriver`. All four instances
share one `ShellProcessRegistry` and one `WorkspacePermissionManager`
reference, constructed once by `ShellModuleDriver`.

## 22.2 The Shell Tool must not implement its own permission logic

Before running any command, `ShellToolDriver` calls
`WorkspacePermissionManager.check(cwd, WorkspaceOperation.EXECUTE)` -
the same shared authority the Filesystem Tool uses (§23). It never
maintains its own permission cache, allow-list, or prompt.

**Execute permission is scoped, not analytical** (see
`Core_Component_Responsibilities.md` §25 for the abstract rule). For
the Shell Tool specifically, this means it must never parse a command
string to infer, restrict, or reason about the filesystem access that
command will perform once it runs - that would duplicate, and could
contradict, the Filesystem Tool's own independent Write/Delete checks
against the same workspace, and shell syntax (`|`, `;`, `&&`,
redirection, subshells, aliases, environment-dependent binaries, ...)
cannot be reliably parsed for this purpose anyway. A command authorized
to run from a trusted workspace can still, for example, write outside
that workspace via its own absolute-path arguments; this is an
accepted, documented boundary, not a defect to fix later inside the
Shell Tool or `PermissionManager`.

## 22.3 `shell.execute` (foreground)

- `command`: `list[str]` (argv form, run with `shell=False` - the safe
  default and never subject to shell-metacharacter injection), or a
  single `str` only when `[shell].allow_shell_string = true` (default
  `false`), run with `shell=True` through the platform default shell -
  an explicit, off-by-default, higher-risk opt-in for callers that
  genuinely need shell features (pipes, globbing, `&&`).
- `cwd`: defaults to `[workspace].default_workspace` when omitted.
- `timeout_seconds`: clamped to `[shell].max_timeout_seconds`
  regardless of what the caller requests - the same clamping shape
  `filesystem.watch`'s `duration_seconds` already uses.
- A timeout is reported as `{"timed_out": true, ...}`, not raised - an
  expected, reportable outcome, not a Tool failure.
- Output is captured, not streamed: a synchronous `ToolRequest ->
  ToolResponse` call has no channel for partial output. Long-running or
  interactive commands should use `shell.background` +
  `shell.processes` instead.

## 22.4 `shell.background` and `shell.processes`

`shell.background` spawns via `subprocess.Popen`, registers the process
under a PARIKA-generated `process_id` (a `uuid4().hex`, not the raw OS
pid, so identity survives pid reuse), and drains stdout/stderr into two
bounded ring buffers (`[shell].output_buffer_max_bytes`, default 65536 -
oldest bytes dropped first, the same bounded-collection shape
`filesystem.walk`'s `max_walk_entries` already uses) via one daemon
reader thread per pipe. `shell.processes` lists every tracked process
(id, command, cwd, pid, status, started_at, exit_code) or, given a
`process_id`, returns that one record plus its captured output tail. It
is read-only and performs no permission check, mirroring the
Filesystem Tool's own read-class operations (§23.1).

## 22.5 `shell.kill`

Escalates via `psutil` (already a project dependency, already used by
`ResourceManager` for CPU/memory/disk stats - this is its first use for
process control): `terminate()`, wait up to
`[shell].kill_grace_period_seconds` (default `5.0`), then `kill()` on
timeout. Scoped to processes this same `ShellProcessRegistry` spawned -
an unknown/foreign pid is rejected, not attempted.

## 22.6 Configuration

```toml
[shell]
enabled = false                # explicit opt-in; falls back to the existing
                                # [security].allow_shell_commands when [shell]
                                # is absent from every configuration layer
default_timeout_seconds = 30.0
max_timeout_seconds = 300.0
max_background_processes = 20
output_buffer_max_bytes = 65536
kill_grace_period_seconds = 5.0
allow_shell_string = false
inherit_environment = true
```

## 22.7 Errors

`ShellToolError` base, with `InvalidShellArgumentError`,
`ShellPermissionDeniedError` (raised when `WorkspacePermissionManager`
denies `Execute`), `UnknownProcessError`, and
`ShellBackgroundLimitExceededError` - uniformly wrapped into
`ToolExecutionError` by `ToolManager.execute()`, exactly like every
existing Tool's own exception hierarchy (§10).

---

# 23. Filesystem Tool: Workspace-Based Access Model

The Filesystem Tool (§17-21 establish its existing shape) is extended,
not redesigned: the same thirteen operations, the same one-Tool-per-
Capability registration, the same `PathSecurity` choke point every path
passes through.

## 23.1 Reads are always allowed; writes/deletes are workspace-gated

| Operation class | Behavior |
|---|---|
| Read-class (`read`, `list`, `search`, `walk`, `info`, `permissions`, `exists`, `watch`, `copy`-source) | Always allowed, any resolvable host path, unconditionally. No workspace check, no prompt. |
| Write-class (`write`, `mkdir`, `copy`-destination, `move`-destination) | Allowed instantly inside a trusted workspace; otherwise delegated to `WorkspacePermissionManager.check(path, WorkspaceOperation.WRITE)` (§23.3). |
| Destructive (`delete`, `move`-source) | Same as write-class, with `WorkspaceOperation.DELETE`; still additionally gated by `[filesystem].allow_delete` as today's coarse kill-switch. |

This is an explicit, spec-mandated posture change from the Filesystem
Tool's original deny-by-default reads. It adds no read-restriction knob
of any kind: if additional read restrictions are ever required, they
belong to `PolicyEngine`, not the Filesystem Tool or `PermissionManager`
(see `Core_Component_Responsibilities.md` §24-25).

## 23.2 `trusted_workspaces` replaces `allowed_roots`

```toml
[workspace]
default_workspace = "data"        # single named source of truth

[filesystem]
trusted_workspaces = []           # empty => only default_workspace is trusted
allow_write = true
allow_delete = false
# allowed_roots = [...]           # deprecated alias, still read if
                                   # trusted_workspaces is absent from
                                   # every configuration layer
```

`[workspace].default_workspace` is always included in the effective
`trusted_workspaces` set, whether or not it is also listed explicitly -
this is what "the default workspace is automatically trusted" means
concretely. It is read once, in one place, and reused by both the
Filesystem Tool and the Shell Tool's default `cwd` (§22.3) - not
duplicated as a second, independent literal the way `[data].directory`
and `[filesystem].allowed_roots` each separately hardcode `"data"`
today.

See `Core_Component_Responsibilities.md` §25 for what a "workspace"
means precisely and why no workspace path is ever hardcoded - `"data"`
above is only this project's current default, not a fixed value.

## 23.3 `PathSecurity` gains an optional collaborator

```python
class PathSecurity:
    def __init__(self, config: PathSecurityConfig, *,
                 permissions: WorkspacePermissionManager | None = None) -> None: ...

    def resolve(self, raw_path, *, argument_name="path", enforce_roots=True,
                operation: WorkspaceOperation | None = None) -> Path:
        ...  # unchanged symlink-safe resolution + containment check
        # containment failure now optionally delegates to
        # self._permissions.check(resolved, operation) before raising
        # PathNotAllowedError
```

`permissions=None` (the default for any caller that does not inject
one) preserves today's exact hard-deny-outside-the-allow-list behavior
- a zero-risk default for any code not yet updated to pass one.
`PathSecurity`'s existing symlink-escape defense
(`Path.resolve()`-then-contain) is unchanged and reused as-is; this
extension only changes what happens when containment fails.

## 23.4 Binary file support

`operations.read`/`operations.write` gain an additive, opt-in `binary`
argument (default `False`, preserving every existing call and test
byte-for-byte):

```python
def read(path, *, encoding="utf-8", binary=False):
    if binary:
        data = path.read_bytes()
        return {"content_base64": base64.b64encode(data).decode("ascii"), ...}
    ...  # unchanged text path

def write(path, *, content="", content_base64=None, encoding="utf-8", binary=False, ...):
    if binary:
        data = base64.b64decode(content_base64 or "")
        # same atomic temp-file + os.replace() sequence already used for text
    ...  # unchanged text path
```

Uses the stdlib `base64` module - no new dependency. This gives PARIKA
raw byte-level read/write access to every listed file type, including
the binary document formats (PDF, DOCX, XLSX, PPTX, ODT, ODS).
**Scope note:** this is raw byte-level access only, not content
extraction/parsing (e.g. turning a PDF into text) - that is a
domain-specific capability for a future, dedicated tool, not the
Filesystem Tool.

---

# 24. Coding Tool

**Status note:** implemented, tested (`tests/tools/coding/`,
`tests/modules/coding/`), and wired into `build_default_runtime()` via
the Coding Module. Provides semantic understanding of source code --
it is explicitly **not** a filesystem tool. Package:
`parika/tools/coding/`; registration Module: `parika/modules/coding/`.

## 24.1 Operations

One Tool per Capability, the same shape §21 establishes; the Filesystem
and Shell Tools are its direct templates. `category=CapabilityCategory
.TOOL`, `tags={"coding", "development"}`.

| Operation | Capability id | Purpose |
|---|---|---|
| `PARSE` | `coding.parse` | Parses one file and stores its index. |
| `SYMBOLS` | `coding.symbols` | Lists indexed symbols for a file (lazily indexes on first call). |
| `SEARCH` | `coding.search` | FTS5 BM25 search over symbol names/signatures/docstrings. |
| `REFERENCES` | `coding.references` | Every reference to a given symbol. |
| `CALL_HIERARCHY` | `coding.call_hierarchy` | Callers and/or callees of a symbol. |
| `IMPORTS` / `DEPENDENCIES` | `coding.imports` / `coding.dependencies` | A file's imports / deduplicated dependency set. |
| `RENAME_PLAN` / `REFACTOR_PLAN` | `coding.rename_plan` / `coding.refactor_plan` | Computed edit lists -- read-only proposals, never applied. |
| `PATCH_GENERATE` | `coding.patch_generate` | Renders an edit list into a unified diff + full new content; performs no I/O. |
| `DOCUMENT` | `coding.document` | Deterministic docstring draft from a symbol's signature -- never an LLM call. |
| `FORMAT` / `LINT` | `coding.format` / `coding.lint` | Dispatches to an already-installed external formatter/linter **through `shell.execute`**. |
| `COMPLEXITY` / `DUPLICATES` / `DEAD_CODE` | `coding.complexity` / `.duplicates` / `.dead_code` | Deterministic static-analysis heuristics. |
| `PROJECT_SUMMARY` | `coding.project_summary` | Structural file/symbol/language counts for a root. |
| `GRAPH_QUERY` / `IMPACT_ANALYSIS` | `coding.graph_query` / `.impact_analysis` | Bounded-depth call-graph traversal, forward/reverse. |

## 24.2 Never a filesystem tool

Every operation is read-only with respect to source files. Mutation is
always performed by the existing, unmodified Filesystem Tool, invoked
by whichever caller (typically the Coding Agent, see `Module_Guide.md`
§18.3) applies a `coding.patch_generate` result via
`filesystem.write`. The Coding Tool itself never depends on
`WorkspacePermissionManager` -- it has nothing to be permission-checked,
because it performs no writes. `coding.format`/`coding.lint` are the
only operations with any external side effect, and they cause it
exclusively by dispatching to `shell.execute` through `ToolManager`
(the same "Tool -> Core -> Tool" shape `CodingAgentToolDriver` also
uses, §25 below) -- never by spawning a process themselves.

## 24.3 `LanguageAnalyzer`: the plugin extension point

`parika/tools/coding/analyzers/protocol.py` defines `LanguageAnalyzer`
(`language_ids()`, `supports(path)`, `parse(path, text)`,
`formatter_command(path)`, `linter_command(path)`) -- the same
"Protocol + registry + default implementations" shape §18.4 already
establishes for Web Search providers. `LanguageAnalyzerRegistry`
resolves a path to the first matching analyzer:

1. `PythonAstAnalyzer` -- stdlib `ast`, always available.
2. One `TreeSitterAnalyzer` per language beyond Python -- requires the
   optional `coding` dependency group (`tree-sitter`,
   `tree-sitter-language-pack`; `pip install parika[coding]`).
   `analyzer.available` reports `False`, and `supports()` returns
   `False`, when that extra is not installed, so the registry falls
   back to (3) transparently -- never a crash, never registered at all
   when unavailable, mirroring `Tool_Guide.md` §18.4's
   `is_available()` check for `google_cse`.
3. `GenericTextAnalyzer` -- regex/line-based TODO/FIXME extraction,
   matches every file, the fallback of last resort.

Adding a new language: write one new `LanguageAnalyzer`, add one entry
to `default_analyzers()`'s tuple. Zero changes to `ToolManager`,
`Planner`, `CapabilityExecutor`, or any other analyzer.

## 24.4 Index storage

`CodingIndexStorage` (`parika/tools/coding/storage.py`) owns
`coding_index.sqlite3` (`coding_files`, `coding_symbols`
+ FTS5, `coding_references`, `coding_imports`, `coding_call_edges`,
`coding_annotations` + FTS5) -- the same WAL/`busy_timeout`
pragmas and external-content-FTS5 pattern every other SQLite store in
this codebase already uses (`MemoryStorage`, `KnowledgeUnitStorage`).
Symbol/reference/call resolution is a deliberate, coarse heuristic
(matching by plain name across the whole index), not full semantic/
type-aware resolution -- chosen over embedding a full Language Server
per language for the same "local-first, dependency-light" reasons
`Core_Component_Responsibilities.md` favors elsewhere.

`repository_intelligence`'s `RepositoryKnowledgeEngine` (see
`Module_Guide.md` §18.2) reuses this same storage instance directly --
a plain Python object reference passed at composition-root wiring
time, not a Module-to-Module dependency, since `parika/tools/coding/`
has no Module identity or driver of its own.

---

# 25. Progress Reporting Convention

Any Tool operation that performs real, potentially-visible work (an
index pass, a long-running command, a multi-file search) should report
its own progress through `parika.core.utilities.progress
.ProgressReporter` -- the generic, ecosystem-wide mechanism introduced
for the Developer Intelligence Platform (see
`Core_Component_Responsibilities.md` §5). This is additive and
optional: a `ToolDriver` that omits it behaves exactly as before.

```python
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

class MyToolDriver:
    def __init__(self, *, progress_reporter: ProgressReporter | None = None) -> None:
        self._progress = progress_reporter or NullProgressReporter("my.capability")

    def execute(self, request):
        self._progress.started(message="Doing the real thing...")
        try:
            ...  # the actual work
            self._progress.progress(current=5, total=10)
        except Exception:
            self._progress.failed()
            raise
        self._progress.completed(message="Completed.")
        return response
```

Rules:

- **Report your own work, never narrate someone else's.** A driver that
  orchestrates other Tools (e.g. `CodingAgentToolDriver`) reports only
  its own real phases (selecting an agent, waiting for a model); it
  never invents descriptive text on behalf of the Filesystem/Shell/
  Coding Tool -- those report their own progress directly.
- **`source_id` stays a stable, generic identifier** (usually the
  Capability id) describing what *kind* of step is reporting, reused
  identically across every instance of that step; instance-specific
  identity (which file, which repository) goes in `**metadata`, never
  appended into `source_id`.
- **Nesting** is `reporter.child("some.step")`, which returns a new
  reporter one level beneath the current one -- no new event name, no
  new mechanism; see `parika/modules/repository_intelligence/indexing
  /repository_knowledge_engine.py` for a three-level example
  (workspace -> repository -> file-scanning).
- **Never block on a subscriber.** `EventBus.publish()` is a cheap,
  synchronous, in-process call; a `ProgressReporter` with no
  subscribers costs one dict lookup per stage transition.

Every `started()`/`progress()`/`completed()`/`failed()` call publishes
to two `EventBus` channels: `"<source_id>.<stage>"` (a specific
channel for a subscriber that wants exactly one operation) and
`"progress.<stage>"` (four fixed, permanent, generic channels covering
every present and future Tool/Module -- subscribe once, receive
everything, filter by `event.source_id`).

---

# Related Documentation

- architecture/PARIKA_Architecture_Specification_v1.0.md
- architecture/Core_Component_Responsibilities.md
- architecture/PARIKA_Decision_Flow.md
- development/Module_Guide.md
- development/Capability_Guide.md
- development/Integration_Checklist.md
- guides/Running.md
- guides/Testing.md
