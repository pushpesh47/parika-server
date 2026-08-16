# ADR 0001: Runtime/System Telemetry via `ResourceManager` and `GET /api/v1/status`

## Context

The PARIKA Web Client (a pure HTML5/CSS/JavaScript presentation layer
over the existing Python server) needs to display accurate, live
system/runtime information: CPU, RAM, GPU/VRAM, temperatures, storage,
network, and PARIKA's own runtime/lifecycle/component counts. Before
this change, `ResourceManager` already provided on-demand CPU,
memory, disk, GPU (stub), network (hostname-only), and filesystem
information -- consumed exclusively by `Planner.plan()` for
model-selection resource filtering -- and `GET /api/v1/status`
already mirrored the `/status` CLI command's lifecycle/health/
module/capability/tool/provider counts, but neither exposed hardware
utilization, GPU telemetry, temperatures, storage/network statistics,
or PARIKA version/memory/knowledge counts.

The architecture is frozen: `ResourceManager`, `HealthManager`, and
`MetricsManager` each already have a defined, non-overlapping
ownership boundary (see
`docs/architecture/Core_Component_Responsibilities.md` sections 8,
22, and 23), and `ResourceManager` is explicitly on-demand, never
continuous, never caching, and never publishing events.

## Decision

1. **Extend `ResourceManager`, do not create a new manager.**
   `CPUInfo`/`MemoryInfo`/`DiskInfo`/`GPUInfo`/`NetworkInfo` gained
   additional fields (load averages, frequency, swap, usage
   percentages, multi-device GPU support, per-interface network
   counters), and two new immutable models were added:
   `TemperatureInfo` (non-GPU thermal sensors) and `SystemInfo`
   (platform/OS/architecture/hostname/boot time/uptime). Both are new
   fields on the existing `ResourceSnapshot`. No new manager, no new
   `SystemMonitorManager`, no parallel resource-monitoring subsystem.

2. **GPU telemetry uses the optional NVIDIA NVML backend** (the new
   `gpu` extra, `nvidia-ml-py`) only when installed and enabled via
   `resources.gpu_telemetry_enabled`. It is never a hard dependency:
   any import failure, NVML initialization failure, or absence of a
   supported GPU degrades to `GPUInfo(status=UNKNOWN/UNAVAILABLE,
   detected=False)` rather than raising or blocking startup. The data
   model (`GPUInfo`/`GPUDeviceInfo`) makes no NVIDIA-specific
   assumption, even though NVML is the only backend implemented today.

3. **`ResourceManager` remains purely on-demand.** No scheduler,
   background thread, or `EventBus` publication was introduced.
   `GET /api/v1/status` and the `/status` CLI command each perform one
   fresh `get_resource_snapshot()` read per invocation, exactly like
   `Planner.plan()` already did. A Web Client is expected to poll the
   API on its own schedule; the recommended interval is exposed as
   `resources.recommended_client_poll_interval_seconds` in
   `config/defaults.toml` (default `5.0` seconds) rather than hardcoded
   in documentation only.

4. **`GET /api/v1/status` is extended, not duplicated.** A separate
   `GET /api/v1/runtime` endpoint was considered (per the milestone's
   suggested conceptual name) but rejected: `/api/v1/status` already
   owned the equivalent "aggregate runtime snapshot" concept and
   already mirrored the `/status` CLI command; adding a second
   endpoint would have meant two competing sources of the same
   information. `StatusResponse` gained additive, backward-compatible
   nested groups: `system`, `cpu`, `memory` (host RAM), `gpu`,
   `temperature`, `storage`, `network`, and `parika` (version,
   provider availability, model counts, long-term Memory/Knowledge
   statistics not already flat fields on the response). Every existing
   flat field (`lifecycle_state`, `overall_health`,
   `registered_tools`, ...) is unchanged.

5. **`overall_health` and hardware telemetry stay on two independent
   axes.** `HealthManager.overall_status()` continues to aggregate
   only registered component health checks; it does not consult
   CPU/memory/GPU numbers, and `ResourceManager` does not register
   itself with `HealthManager` or ask it anything. The two are
   reported side by side in the same response, never merged into one
   value, per the milestone's explicit requirement not to produce "one
   misleading health value".

6. **`MetricsManager` is not wired into telemetry collection.** It
   remains a dependency-free counters/gauges/timings store with zero
   production callers, unchanged by this work, preserving its existing
   ownership boundary rather than introducing a new coupling for a
   single feature.

7. **Hostname is redacted by default at the API layer.**
   `ResourceManager` continues to populate `SystemInfo.hostname`/
   `NetworkInfo.hostname` unconditionally (every existing caller, e.g.
   the CLI running on the user's own machine, still sees the real
   value), but `GET /api/v1/status` reports `null` for both unless an
   operator explicitly sets `api.expose_hostname = true`, since the
   REST API -- unlike the CLI -- may be reachable from other devices
   on a LAN or the Internet.

8. **CLI `/status` gains new System/CPU/RAM/GPU/Temperature/Storage/
   Network sections** (`_status_hardware_lines` in
   `parika/interfaces/commands/builtin.py`), sourced from the same
   `ResourceManager.get_resource_snapshot()` call as the API. No new
   slash command was added: `/status` was judged sufficient, and a
   dedicated `/runtime` command would have duplicated it.

## Alternatives Considered

- **A new `SystemMonitorManager`/`TelemetryManager`.** Rejected: would
  duplicate `ResourceManager`'s existing, frozen responsibility and
  introduce a second on-demand hardware-reading component with no
  clear boundary against the first.
- **A dedicated `GET /api/v1/runtime` endpoint.** Rejected in favor of
  extending `/api/v1/status` (see Decision 4) to avoid two competing
  sources of the same "aggregate runtime snapshot" concept.
- **Continuous background polling + `EventBus` publication (e.g.
  `runtime.telemetry.updated`).** Rejected for this increment:
  `ResourceManager`'s documented on-demand design explicitly avoids a
  poller that runs whether or not anything is currently reading it,
  and no `Scheduler` job currently exists in `build_default_runtime()`
  to host one. A polling Web Client, calling the now-richer
  `GET /api/v1/status`, meets the milestone's live-telemetry
  requirement without adding a second event-publication path
  alongside the existing generic `progress.*` family. This can be
  revisited as a follow-up increment if/when the `Scheduler` is wired
  into the runtime for other reasons.
- **A non-NVIDIA GPU backend (AMD ROCm-SMI, Intel, generic
  `torch.cuda`).** Rejected for this increment: no such dependency was
  already present in the project, and adding one was not necessary to
  satisfy the milestone. The data model does not assume NVIDIA
  hardware, so a future backend can be added without another schema
  change.

## Consequences

- `ResourceManager`'s public surface grew (new fields, two new models,
  no removed fields) but its existing consumer (`Planner`'s resource
  filtering, via `snapshot.gpu.status`/`snapshot.memory
  .available_bytes`/`snapshot.disk.free_bytes`) continues to work
  unchanged; `GPUInfo.status` retains its original `ResourceStatus`
  semantics.
- `GET /api/v1/status` responses are larger. Per the project's
  existing API Stability Rules (`docs/guides/Running.md` section
  12.9), this is backward compatible: every new field is additive,
  and `ApiModel`'s `extra="ignore"` means older clients are unaffected
  either way.
- A new optional dependency group (`gpu`, `nvidia-ml-py`) was added to
  `pyproject.toml`. It is never required for PARIKA to install, start,
  or run.
- A new configuration section (`[resources]`) and one new key under
  `[api]` (`expose_hostname`) were added to `config/defaults.toml`,
  following the project's existing enable-flag/interval-config
  conventions.
