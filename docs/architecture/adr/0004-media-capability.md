# ADR 0004: Provider-Independent Media Capability (`media.*` Capabilities/Tools + `WS /api/v1/ws/media/{client_id}`)

## Context

PARIKA needs to let a user say or type commands such as "Play
Imagine Dragons Believer", "Play this YouTube video", "play any south
indian movies from youtube", "Play the song in
/home/pushpesh/Music/test.mp3", "Pause", "Resume", "Skip", "Set volume
to 50%", "Show the video", and "Stop playing", and have those commands
actually control media playback. The PARIKA Web Client (a **separate,
future project/repository** - out of scope for this change entirely)
will implement the actual player. PARIKA's job is therefore narrower
than "add a media player": resolve intent, resolve a playable source,
and maintain a synchronized command/state protocol with whatever Web
Client happens to be connected.

The architecture is frozen: the 28-component Core Implementation
Order (`docs/architecture/PARIKA_Architecture_Specification_v1.0.md`
section 5.1) is not extended - Media is a Module/Tool pair, exactly
like Voice (`0002-voice-capability.md`) and Expense Management
(`0003-expense-management.md`), not a new Core component. Three
things already exist that this change reuses rather than
reimplements: the `web.search` Capability
(`parika/tools/web_search/`), the nested-Goal-via-`Brain.handle()`
pattern for one Tool to reuse another Capability
(`parika.modules.voice.engine`), and the Expense Tool's "one Tool per
Capability, dispatch-table-per-operation" shape
(`parika/tools/expense/driver.py`).

One thing does **not** already exist: a realtime transport a Core
component can use to push an unsolicited message to an open
connection. The only existing WebSocket route,
`WS /api/v1/ws/chat/{session_id}` (`parika/api/ws/chat.py`), is
hardwired to chat's own inbound/outbound message shapes, keeps no
registry of open connections, and only ever writes to the socket
*inside* its own single receive loop - there is no existing mechanism
for a synchronous `ToolDriver` to deliver a command to a Web Client at
an arbitrary time. Core itself remains fully synchronous by design
(confirmed directly: `TaskManager.execute()` calls
`CapabilityExecutor.execute()` inline and blocks until it returns;
`WorkflowEngine` is unfinished scaffolding, `_execute_step()` still
raises `NotImplementedError`, and is not wired into
`build_default_runtime()` at all).

## Decision

1. **Media is a Module/Tool pair, not a new Core component or a
   parallel architecture.** `parika/modules/media/` (manifest +
   `MediaModuleDriver`, registration/lifecycle only) and
   `parika/tools/media/` (domain model, resolution, security, state,
   connection registry, and `MediaToolDriver`) follow the exact
   module/tool split every other Module already uses
   (`docs/development/Module_Guide.md` section 3;
   `parika/modules/expense/driver.py`'s own docstring for the
   precedent). `MediaModuleDriver.start()`/`stop()` only register/
   unregister Capabilities and Tools - see
   `tests/modules/media/test_module_driver.py`.

2. **Thirteen `media.*` Capabilities, one Tool each, one shared
   dispatch-table-bound `MediaToolDriver` class.**
   `media.play`/`pause`/`resume`/`stop`/`skip`/`previous`/`seek`/
   `set_volume`/`mute`/`unmute`/`show`/`hide`/`get_state`
   (`parika/tools/media/manifest.py`'s `MediaOperation` enum), each
   registered with `category=CapabilityCategory.TOOL` (there is no
   `media` `CapabilityCategory` member - see
   `parika/core/capability_registry/capability_category.py` - and
   none was added; every model-advertised Capability in this
   repository already uses `TOOL`, per
   `docs/development/Capability_Guide.md` section 3). This mirrors
   `parika/tools/expense/driver.py`'s exact "one `ExpenseToolDriver`
   instance bound to one `ExpenseOperation` at construction,
   dispatch-table `_HANDLERS`" shape - see
   `parika/tools/media/driver.py` and
   `tests/tools/media/test_driver.py`.

3. **PARIKA server never plays, decodes, streams, downloads, or
   transcodes audio/video, and never will under this Capability.**
   `parika/tools/media/driver.py`'s module docstring states this
   explicitly. Every command handler returns either
   `"status": "dispatched"` (a command was handed to a connected Web
   Client) or `"status": "unavailable"` (no Web Client connected) -
   never a claim that playback happened. `media.get_state` is a pure
   read of `MediaStateStore`, never a command dispatch. See
   `tests/tools/media/test_driver.py::TestPlay
   ::test_play_reports_unavailable_without_a_connected_client`.

4. **A provider-independent `MediaSource`/`MediaState` domain model,
   not a YouTube-specific one.** `parika/tools/media/model.py`
   defines `MediaSourceType` (`local`/`youtube`/`direct_url`/
   `stream`) and an immutable `MediaSource` dataclass whose
   `__post_init__` enforces the minimum required fields per type
   (mirroring `parika/tools/expense/model.py`'s `Expense.to_dict()`
   convention: a plain, JSON-serializable `to_dict()`, never a raw
   YouTube-extracted media URL - see Decision 8). `MediaState`
   (`status`, `source`, `position`, `volume`, `muted`,
   `playback_rate`, `visible`, `client_connected`, `error_message`,
   `updated_at`) is PARIKA's *last known* playback state, never a
   claim of current, live browser truth - see Decision 7.

5. **Media intent, resolution, and the playback command are three
   distinct steps, and resolution is a swappable abstraction, not
   hardcoded YouTube logic inside the Capability.**
   `parika/tools/media/resolution.py`'s `MediaResolver.resolve(query)`
   tries, in order: (a) a local filesystem path (see Decision 6), (b)
   a URL, classified as a recognized YouTube link, a direct playable
   media file, or a stream manifest by extension/host - never an
   arbitrary webpage - and (c), only for free text with no local/URL
   match, a fallback to the existing, unmodified `web.search`
   Capability via exactly the same nested-`Goal`-via-`Brain.handle()`
   shape `parika.modules.voice.engine` already establishes for
   reusing `filesystem.read`/`filesystem.write` (never a second
   reasoning path, never a YouTube Data API key, never `yt-dlp`). A
   YouTube Data API-backed (or any other) resolver could later be
   substituted without touching `driver.py` at all, since it depends
   only on `MediaResolver.resolve()`'s return type. See
   `tests/tools/media/test_resolution.py`.

6. **Local media is confined to an explicit, empty-by-default
   allowlist, never PARIKA's own unconditional filesystem-read
   posture.** `parika/tools/media/security.py`'s
   `LocalMediaPathSecurity` mirrors
   `parika/tools/filesystem/security.py`'s `PathSecurity` choke-point
   shape (validate -> resolve symlinks/`..` -> containment check) but
   is deliberately *narrower*: Filesystem's own `read`/`list`/etc.
   permit any host path unconditionally
   (`enforce_roots=False`) by design, but a resolved `MediaSource`'s
   raw `path` is returned to the caller/model and potentially
   surfaced to a Web Client, so an unconstrained local resolver would
   let a caller probe for the existence of arbitrary filesystem paths
   merely by asking to "play" them. `[media].allowed_local_roots` is
   `[]` by default (local media resolution disabled until an operator
   opts in), and PARIKA never implements a filesystem-serving HTTP
   endpoint for the Web Client to fetch bytes from - see Decision 13
   below and `docs/guides/Running.md`'s Media API section, "Local
   files".

7. **The separate Web Client is the sole authority on actual
   playback; PARIKA only ever holds its last reported state.**
   `parika/tools/media/state_store.py`'s `MediaStateStore` is a
   thread-safe, shared-singleton-via-`ServiceContainer` holder
   (exactly the `TtsOperationRegistry`/`VoiceLanguagePreferenceStore`
   pattern from Voice - constructed once at the composition root,
   injected into both `MediaToolDriver` and the Media API/WebSocket
   layer, so both read/write the identical instance). Dispatching
   `media.play` only ever moves the locally-held status to `LOADING`
   - never `PLAYING` - and every other command leaves `status`
   untouched; only an inbound Web-Client-reported event
   (`media.play_started`/`media.state_changed`/etc.,
   `MediaStateStore.apply_client_event()`) advances it further. See
   `tests/tools/media/test_state_store.py`.

8. **YouTube is a special, non-extracted source type; PARIKA never
   resolves a raw YouTube media URL.** A `youtube` `MediaSource`
   carries `url`/`media_id`/descriptive metadata only - the Web
   Client is expected to render it with an official YouTube-supported
   browser integration (e.g. the IFrame Player API), never a
   PARIKA-extracted MP4/MP3 stream. No `yt-dlp` or YouTube Data API
   dependency was added (see Decision 5 and the "Dependencies"
   consequence below).

9. **A new, minimal, additive WebSocket route -
   `WS /api/v1/ws/media/{client_id}` - because no existing transport
   could be reused without modifying/duplicating chat's own
   hardwired shape.** `parika/api/ws/media.py` follows `ws/chat.py`'s
   exact auth/accept mechanics (same credential-extraction helper,
   same `close(code=1008)` on failed auth) but adds two things chat
   does not have: a connection registry
   (`parika/tools/media/connection_registry.py`'s
   `MediaConnectionRegistry`, holding an `asyncio.Queue` + event loop
   handle per connection) and an independent send loop, so a command
   can be pushed to a Web Client at any time - not only in response
   to an inbound message, as chat's own single receive loop requires.
   `ws/chat.py` itself is untouched. See
   `tests/api/ws/test_media_ws.py`.

10. **Command dispatch is non-blocking with respect to the rest of
    PARIKA's (synchronous) request processing, by construction, not
    by a new concurrency architecture.** `MediaConnectionRegistry
    .dispatch()` never awaits and never blocks on delivery or
    confirmation: it only calls
    `loop.call_soon_threadsafe(queue.put_nowait, message)`, which
    schedules delivery and returns immediately regardless of whether
    the target connection's own send loop is currently busy, slow, or
    has not run at all yet. This was chosen deliberately over
    `TaskManager`/`WorkflowEngine`: this increment's own architecture
    audit confirmed `TaskManager.execute()` itself blocks inline on
    `CapabilityExecutor.execute()` (no background thread pool exists
    anywhere in Core), and `WorkflowEngine` is unfinished scaffolding
    not wired into `build_default_runtime()` at all - neither would
    have made `media.play` non-blocking; the connection-registry-level
    fix does. See `tests/tools/media/test_connection_registry.py
    ::TestNonBlockingDispatch` and
    `tests/tools/media/test_driver.py::TestNonBlockingPlay` for the
    deterministic proof (a target event-loop thread deliberately
    monopolized by a tight, non-yielding loop; dispatch still returns
    in well under the test's bound, and an entirely unrelated Tool
    call executes immediately afterward through the same
    `ToolManager`).

11. **`GET /api/v1/media/state` is a direct `ServiceContainer` read,
    never a Planner/Brain/`ToolManager` round trip - mirroring Voice's
    own `GET /api/v1/voice/settings` precedent
    (`parika/api/handlers/voice.py::handle_voice_get_settings()`).**
    `parika/api/handlers/media.py` reads the shared `MediaStateStore`
    directly, since this is a pure state read, not a capability
    execution - see `parika/api/handlers/__init__.py`'s
    orchestration/translation-only rule. It is registered through
    the existing `Router` Core component exactly like every other
    REST endpoint (`parika/api/router_bindings.py`'s `media.get_state`
    Route).

12. **Unknown source types and unknown WebSocket event types fail
    clearly rather than being silently misinterpreted, for forward
    compatibility.** `MediaSource.__post_init__` raises `ValueError`
    for an incomplete/invalid combination; `MediaState
    .apply_client_event()` treats an unrecognized `event_type` as a
    no-op state read (never guesses a mapping); `ws/media.py` replies
    `{"type": "error", ...}` over the same socket for an unrecognized
    inbound `type` rather than disconnecting the Web Client - a
    forward-compatible Web Client sending a message type PARIKA does
    not yet know about must not be dropped for it. Adding a new
    `MediaSourceType` member remains a breaking wire-format change
    for existing Web Clients, exactly like adding a new field to any
    other frozen API schema in this codebase (see
    `docs/guides/Running.md` section 12.9's API stability rules,
    which this Capability follows identically for both REST and
    WebSocket messages).

13. **No speculative feature was implemented.** No media downloading,
    transcoding, caching, media library database, playlist database,
    recommendation engine, YouTube downloader, audio extraction,
    server-side waveform generation, or media proxy/filesystem-serving
    endpoint exists anywhere in this change - see the "Intentionally
    Deferred" section below.

## Alternatives Considered

- **Add a `media`/`playback` `CapabilityCategory` member.** Rejected:
  every model-advertised Capability across the entire codebase already
  uses `CapabilityCategory.TOOL` (Voice's own `SPEECH`/`TEXT_TO_SPEECH`
  categories exist only for its *internal*, Provider-routed
  Capabilities, never the advertised ones - see
  `parika/modules/voice/module_driver.py`'s own comment on this exact
  point). Media has no Provider-routed sub-Capability at all (nothing
  here goes through `ProviderManager`/`ExecutionBackend.PROVIDER`), so
  there is no analogous internal category to introduce either.

- **Implement actual playback (decode/stream audio-video) inside
  PARIKA, e.g. with a Python media library.** Rejected outright by
  the task's own core architectural decision, and for sound
  independent reasons: it would make the PARIKA server a media
  streaming/transcoding service, add a large native dependency
  surface (`ffmpeg`/codec bindings) for a concern that belongs to a
  browser, and could not serve a video *surface* to the user at all
  without a second, entirely separate rendering path duplicating what
  a browser already does natively.

- **Hardcode YouTube search/resolution (a YouTube Data API client or
  `yt-dlp`) directly inside `MediaToolDriver`/`resolution.py`.**
  Rejected: the task explicitly forbids designing around `yt-dlp` or
  a raw extracted media URL, and a hardcoded provider client would
  violate the same "no YouTube-specific logic inside the core Media
  Capability" requirement Decision 5 satisfies by delegating to the
  existing, provider-agnostic `web.search` Capability instead. A
  YouTube Data API-backed resolver remains a valid *future*, purely
  additive `MediaResolver` implementation if ever required - nothing
  in `driver.py` would need to change.

- **Reuse/extend `WS /api/v1/ws/chat/{session_id}` for media
  events instead of a new route.** Rejected: chat's handler has no
  message-type dispatch, no connection registry, and only ever writes
  to the socket from inside its own single receive loop (see Context);
  teaching it to also carry `media.*` frames would require the exact
  same connection-registry/send-loop additions this ADR introduces
  anyway, just bolted onto an unrelated, already-shipped chat
  contract, and would risk destabilizing
  `tests/api/ws/test_chat_ws.py`'s existing guarantees for no
  benefit - a second small, independent route is strictly additive
  and keeps both contracts simple.

- **Route `media.play` execution through `TaskManager`/
  `WorkflowEngine` to satisfy the "non-blocking" requirement.**
  Rejected after directly inspecting both: `TaskManager.execute()`
  itself calls `CapabilityExecutor.execute()` synchronously and
  blocks until it returns (there is no background thread pool
  anywhere in Core), and `WorkflowEngine`'s `_execute_step()`/
  `_create_execution()` still `raise NotImplementedError` and it is
  not constructed by `build_default_runtime()` at all. Neither
  primitive would have made dispatch non-blocking; the actual
  blocking risk was always "wait for a Web Client to receive/act on a
  command", which only the connection-registry's `call_soon_threadsafe`
  dispatch-and-forget design (Decision 10) addresses.

- **A broad, filesystem-serving HTTP endpoint so the Web Client could
  fetch local media bytes directly (e.g.
  `GET /api/v1/media/local?path=...`).** Rejected outright per the
  task's explicit security requirement and this ADR's own Decision 6:
  it would let any authenticated caller read arbitrary bytes from any
  allowlisted-root file (or, without a narrow allowlist, arbitrary
  host files) merely by knowing/guessing a path, is unrelated to the
  Media Capability's actual job (resolving/controlling playback
  intent, not serving files), and is explicitly listed as an
  anti-goal in the task. Local-file playback delivery is documented as
  a Web Client integration responsibility (browser File API, a
  user-selected local file, or a narrowly-scoped, separately-designed
  local-media bridge if a future task genuinely requires one) - see
  `docs/guides/Running.md`'s Media API section, "Local files".

## Intentionally Deferred

The following are explicitly out of scope for this change, matching
the task's own "No Unnecessary Features" constraint - each is a
plausible, separate future task, not a gap in this one:

- Media downloading, transcoding, or caching of any kind.
- A media library/playlist database (only a single current
  `MediaState`/source is tracked - see `docs/guides/Running.md`'s
  Media API section on queue support).
- A recommendation engine.
- Server-side audio waveform generation (the Web Client may use
  `wavesurfer.js` client-side - see "GitHub Research" below).
- A YouTube Data API integration (the current free-text resolver uses
  `web.search`; a dedicated API-backed resolver is a valid additive
  future `MediaResolver`).
- A local-media-serving HTTP bridge/endpoint (see "Alternatives
  Considered" above).
- Multi-client "who controls playback" arbitration: every currently
  connected Web Client receives every dispatched command and may
  report state independently; PARIKA does not yet pick one
  authoritative client when more than one is connected. A real
  multi-device scenario is left for a future increment once an actual
  Web Client exists to validate the requirement against.

## GitHub Research (architectural references only - never added as dependencies)

Researched for architectural precedent only, per the task's own
instruction; **none of the following were added as PARIKA server
dependencies**, and no frontend/JavaScript file was created anywhere
in this change:

- **Video.js** - mature HTML5 media-player architecture (adapter
  pattern per source type). Adopted concept: the
  `MediaSourceType`-per-adapter shape informs the "Web Client Media
  Integration Contract" section of `docs/guides/Running.md`
  (`MediaEngine` with `LocalMediaAdapter`/`YouTubeMediaAdapter`/
  `DirectUrlMediaAdapter`), implemented entirely as documentation
  guidance for the future, separate Web Client - no PARIKA server code
  depends on this.
- **videojs-youtube** - confirms that official YouTube-supported
  browser integration (not a raw extracted stream URL) is the correct
  boundary for Decision 8's "YouTube is a special, non-extracted
  source type."
- **hls.js** - confirms `MediaSourceType.STREAM` (a manifest URL, not
  a single file) is a distinct, real category worth keeping separate
  from `DIRECT_URL`, informing this ADR's Decision 4.
- **wavesurfer.js** / **Media Chrome** - confirm audio visualization
  and media control UI are exclusively browser-side concerns; neither
  is mentioned as anything but Web Client implementation guidance in
  documentation.

## Consequences

- **New files:** `parika/modules/media/{__init__,manifest,
  module_driver}.py`; `parika/tools/media/{__init__,model,exceptions,
  security,resolution,state_store,connection_registry,manifest,
  driver,events,config}.py`; `parika/api/schemas/media.py`;
  `parika/api/handlers/media.py`; `parika/api/routers/media.py`;
  `parika/api/ws/media.py`; this ADR; the Media API section of
  `docs/guides/Running.md`; the full `tests/tools/media/`,
  `tests/modules/media/`, `tests/api/routers/test_media_router.py`,
  and `tests/api/ws/test_media_ws.py` test suites.
- **Modified files:** `parika/interfaces/runtime.py` (constructs and
  wires `MediaStateStore`/`MediaConnectionRegistry`/`MediaResolver`/
  `MediaModuleDriver`, registers/loads the Media Module, additively -
  no existing Module's construction changed); `parika/api/requests.py`
  (adds `MediaGetStateRequest`, additive); `parika/api/router_bindings.py`
  (adds the `media.get_state` Route, additive);
  `parika/api/routers/__init__.py` (mounts the two new routers,
  additive); `config/defaults.toml` (adds `[media]`, additive);
  `docs/api/PARIKA_API_Reference.html` (regenerated via
  `python scripts/generate_api_docs.py` to include
  `GET /api/v1/media/state`); three pre-existing tests whose
  assertions hardcoded the exact Module/Route count
  (`tests/api/test_router_bindings.py`,
  `tests/interfaces/commands/test_builtin.py`,
  `tests/interfaces/test_runtime.py`) updated to include Media, with
  no other change to their behavior or intent.
- **No file under `web/` (the existing, unrelated built-in Expense
  Management demo client) was touched**, and no frontend/JavaScript/
  HTML file was created anywhere - the actual future Web Client
  remains entirely out of scope, per the task.
- **No dependency was added to `pyproject.toml`.** Resolution/security
  use only the Python standard library (`urllib.parse`, `mimetypes`,
  `pathlib`) plus the existing `web.search` Capability.
- Every existing Capability/Module/Tool/Route is unaffected; the
  Voice, Expense, Filesystem, and Web Search Capabilities/Tools this
  change reuses or mirrors are unmodified.
- The full test suite (3172 tests as of this change, including the
  88 new Media-specific tests) passes.
