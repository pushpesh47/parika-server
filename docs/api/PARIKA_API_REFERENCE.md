# PARIKA API Reference

**Canonical, code-verified client API reference.** A developer who has
never read the PARIKA source code should be able to read only this
file and successfully integrate a Web, Desktop, CLI, Mobile, or
automation client against the PARIKA Server.

This file is a **hand-written companion** to the auto-generated
[`docs/api/PARIKA_API_Reference.html`](PARIKA_API_Reference.html)
(a Redoc rendering of the live FastAPI OpenAPI schema, produced by
`python scripts/generate_api_docs.py` — **never hand-edit that file**).
The HTML file is the authoritative machine-readable REST schema; this
file adds the two WebSocket protocols (not representable in OpenAPI),
narrative/behavioral detail, authentication/error semantics, and
end-to-end workflows the raw schema cannot express. Where the two
disagree, trust the HTML/OpenAPI schema for REST field-level shape and
this file for behavior — then re-run
`python scripts/generate_api_docs.py` and file a documentation bug.

Everything in this document was verified directly against
`parika/api/`, `parika/server/`, `tests/api/`, `tests/server/`, and
`web/app.js` as of this audit. All 88 tests in `tests/api/` and
`tests/server/` pass against this description.

---

## 1. Introduction

### What the API exposes

The PARIKA Server (`parika/server/`) exposes PARIKA's Core (Router,
Planner, Brain, TaskManager, CapabilityRegistry, ToolManager,
ProviderManager, ModuleManager) to **external clients** over HTTP and
WebSocket. It is a thin, versioned client-facing layer over the same
execution pipeline the PARIKA Console already uses in-process — the
Console (`parika/console/`) never goes through this API and is not
subject to its authentication or rate limiting.

### Intended clients

Any out-of-process consumer: the shipped Web Client (`web/`, a static
Expense Management UI), a future Desktop Client, CLI Client, Mobile
Client (Android/iOS), or other automation/integration client.

### API architecture

- Framework: **FastAPI** (`fastapi>=0.128`), served by **Uvicorn**
  (`uvicorn[standard]>=0.35`). Installed via the optional `server`
  extra: `pip install -e ".[server]"`.
- Every HTTP/WebSocket router lives under `parika/api/`; each handler
  dispatches into Core through a single shared `Router` instance
  (`app.state.router`), never bypassing it except for two documented
  cases: the Expense handlers call `ExpenseService` directly
  (`parika/api/handlers/expense.py`), and the Voice handlers call
  `ToolManager.execute()` with a hard-coded tool id
  (`parika/api/handlers/voice.py`).
- Protocols: **REST/JSON** over HTTP for all resource operations, plus
  **two WebSocket** channels (`/ws/chat/{session_id}`,
  `/ws/media/{client_id}`) for streaming/bidirectional use cases.
  **No SSE endpoints exist anywhere in the codebase.**

### Versioning

- Single path-prefix version: **`/api/v1`** on every route
  (`parika/api/routers/__init__.py`). There is no header-based or
  query-based versioning.
- The FastAPI app's own `version="1.0.0"` (`parika/server/app.py`) is
  the OpenAPI document version, unrelated to the `/api/v1` URL prefix.
- **Stability rules** (see §6.9 for the full policy): once published,
  an endpoint's path is never renamed, existing request fields are
  never removed, and new fields are always optional/backward
  compatible. A breaking change requires a new `/api/v2`, mounted
  alongside — never a modification of `/api/v1`.

### Base URL / deployment

There is **no hardcoded base URL** anywhere in the server. A client
determines it from where it deployed/configured the server:

- Server binds to `[api].host` / `[api].port` in `config/defaults.toml`
  — **defaults: `127.0.0.1:2026`** — overridable per-run with
  `--host`/`--port` CLI flags (`python -m parika.server --port 9000`).
- The shipped Web Client stores its own target base URL in
  `localStorage["parika.expense.apiBaseUrl"]`, defaulting to
  `http://127.0.0.1:2026` (`web/app.js`) — a client-side setting, not
  a server contract.
- All examples in this document use `http://127.0.0.1:2026` (the
  actual configured default) as a placeholder. Substitute your
  deployment's real host/port.

---

## 2. Quick Start

Install and run the server:

```bash
pip install -e ".[server]"
python -m parika.server
# INFO:     Uvicorn running on http://127.0.0.1:2026 (Press CTRL+C to quit)
```

Make your first call (no authentication needed with the default
`[api.auth].mode = "none"`):

```bash
curl http://127.0.0.1:2026/api/v1/health
# {"status": "ok"}
```

Send a chat message:

```bash
curl -X POST http://127.0.0.1:2026/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello"}'
```

```json
{
  "session_id": "5e3f7c8a1e2b4d6c9a0f1b2c3d4e5f60",
  "succeeded": true,
  "message": "Hello! How can I help you today?",
  "error_message": null
}
```

---

## 3. Authentication

### Mechanism (verified: `parika/api/auth/`)

A single global auth policy applies to every route except
`GET /api/v1/health`, `GET /api/v1/live`, and `GET /api/v1/ready`,
which are always unauthenticated. There is **no role/permission
system** — authentication is binary (accepted/rejected); there is no
per-route scope, no admin tier, no ownership check anywhere in the
codebase.

The backend is selected by `[api.auth].mode` in `config/defaults.toml`
at server startup, with **no code change** required to switch:

| Mode | Deployment target | Behavior |
|---|---|---|
| `"none"` (default) | Local development only | Every request accepted unconditionally, `AuthContext(subject="anonymous", mode="none")`. **Never use on a LAN/Internet-facing deployment.** |
| `"api_key"` | LAN | Requires `Authorization: Bearer <key>` or `X-API-Key: <key>`. Keys are configured **hashed** (never plaintext) in `[api.auth].api_keys`. |
| `"jwt"` | Internet | Requires `Authorization: Bearer <token>`, HS256-signed with `[api.auth].jwt_secret`. Verifies `exp`/`sub` claims. |

```toml
# config/defaults.toml
[api.auth]
mode = "none"          # "none" | "api_key" | "jwt"
api_keys = []           # hashed values, see below
jwt_secret = ""
jwt_expiry_seconds = 3600
```

### Credential extraction (identical for HTTP and WebSocket)

- HTTP: checked in order — `Authorization: Bearer <token>` header,
  then `X-API-Key: <key>` header (`parika/api/auth/dependency.py`).
- WebSocket: `Authorization: Bearer <token>` header, then
  `X-API-Key: <key>` header, then a `?token=<value>` **query
  parameter** (the only place a query-param credential is accepted —
  browsers cannot set custom headers on a `WebSocket` constructor
  call).

### Hashing an API key

There is **no token-issuance/login HTTP endpoint**. API keys are
provisioned out-of-band by an operator:

```python
from parika.api.auth import configure_hashed_api_keys
print(configure_hashed_api_keys(["your-plaintext-key"])[0])
# -> paste the printed hash into config/defaults.toml's
#    [api.auth].api_keys list
```

JWTs are likewise only issuable in-process (`JwtBackend.issue_token()`)
— there is no `/auth/login` or `/auth/token` route.

### Example requests

```bash
# api_key mode
curl http://127.0.0.1:2026/api/v1/status -H "X-API-Key: your-plaintext-key"
curl http://127.0.0.1:2026/api/v1/status -H "Authorization: Bearer your-plaintext-key"

# jwt mode
curl http://127.0.0.1:2026/api/v1/status -H "Authorization: Bearer eyJhbGciOi..."
```

### Failure behavior

| Failure | Exception | HTTP status | WebSocket |
|---|---|---|---|
| No credential supplied | `MissingCredentialsError` | 401 | close code **1008** |
| Credential does not match any configured key/secret | `InvalidCredentialsError` | 401 | close code **1008** |
| JWT `exp` claim in the past | `ExpiredTokenError` | 401 | close code **1008** |

Error body (HTTP): the standard error envelope (§8), e.g.:

```json
{"error": {"type": "MissingCredentialsError", "message": "No API key was supplied.", "request_id": "..."}}
```

WebSocket failures **close the connection with code 1008** before
`accept()` is called — no JSON error frame is sent for auth failure
(contrast with in-session errors, which *do* send a JSON error frame
— see §9).

---

## 4. Common Request/Response Conventions

- **Content type:** `application/json` for every request body and
  response body. No multipart/form-data anywhere (audio is base64
  text inside JSON, never a file upload).
- **Path prefix:** every route is under `/api/v1`.
- **Response envelope:** there is **no generic success envelope** —
  each endpoint returns its own flat Pydantic-modeled JSON object
  directly (no `{"data": ...}` wrapper). Unknown extra fields sent by
  a client are **always ignored, never rejected** (`ApiModel`'s
  `extra="ignore"`, `parika/api/schemas/common.py`) — this is the
  forward-compatibility mechanism backing the stability rules in §6.9.
- **Errors:** always the uniform envelope in §8, regardless of which
  endpoint or Core component raised.
- **IDs:** capability/tool/module/provider ids are stable strings
  (e.g. `filesystem.read`, `tool.filesystem_read`, `weather`,
  `provider.ollama`) defined by their respective registrations — not
  UUIDs. Expense ids and error `request_id`s are opaque hex strings
  generated at creation time.
- **Timestamps:** ISO 8601 (`datetime` fields serialize with FastAPI's
  default Pydantic JSON encoding, UTC).
- **Pagination:** only the Expense List/Summary endpoints paginate,
  via `limit`/`offset` query parameters (no cursor-based pagination
  anywhere).
- **Status codes:** `200` success, `422` request validation failure,
  `400`/`401`/`403`/`404`/`409`/`500`/`501` per the error-mapping table
  in §8. No `201 Created` is used anywhere — even `POST /expenses`
  returns `200`.
- **CORS:** `[api.cors].allow_origin_regex` (default: any
  `http://127.0.0.1`/`http://localhost` origin) plus the optional,
  explicitly configured `[api.cors].allow_lan_origin_regex` for a LAN
  Web Client (disabled/empty by default); `allow_credentials=True`,
  all methods and headers allowed (`parika/server/app.py`, see
  `docs/guides/Running.md` section 12.6).
- **Rate limiting:** `[api.rate_limit]` exists in configuration
  (`enabled=false`, `requests_per_minute=600000` by default) but is
  **not enforced by any middleware in the current codebase** — it is
  documented for forward compatibility only. Do not rely on
  server-side rate limiting today.

---

## 5. API Index

All paths below are relative to the base URL and already include the
`/api/v1` prefix. **Auth** column: `none` = always unauthenticated;
`RequireAuth` = subject to `[api.auth].mode` (§3).

| Category | API | Method | Path | Auth | Description |
|---|---|---|---|---|---|
| Health | Health | GET | `/api/v1/health` | none | Always-`200` reachability check |
| Health | Liveness | GET | `/api/v1/live` | none | Event-loop liveness check |
| Health | Readiness | GET | `/api/v1/ready` | none | `200` once runtime constructed, else `503` |
| Status | Status | GET | `/api/v1/status` | RequireAuth | Full runtime + system telemetry snapshot |
| Tools | List tools | GET | `/api/v1/tools` | RequireAuth | Enumerate registered Tools |
| Modules | List modules | GET | `/api/v1/modules` | RequireAuth | Enumerate registered Modules |
| Modules | Start module | POST | `/api/v1/modules/{module_id}/start` | RequireAuth | Load/activate a Module |
| Modules | Stop module | POST | `/api/v1/modules/{module_id}/stop` | RequireAuth | Unload/deactivate a Module |
| Capabilities | List capabilities | GET | `/api/v1/capabilities` | RequireAuth | Enumerate registered Capabilities |
| Capabilities | Execute capability | POST | `/api/v1/capabilities/{capability_id}/execute` | RequireAuth | Generic fallback invocation (Tool-backed capabilities only) |
| Providers | List providers | GET | `/api/v1/providers` | RequireAuth | Enumerate registered Providers + models |
| Config | Get config | GET | `/api/v1/config` | RequireAuth | Read-only Configuration inspection |
| Config | Reload | POST | `/api/v1/reload` | RequireAuth | Reload Modules + refresh Provider health/models |
| Expenses | Create | POST | `/api/v1/expenses` | RequireAuth | Create an expense record |
| Expenses | List | GET | `/api/v1/expenses` | RequireAuth | Filter/paginate expense records |
| Expenses | Summary | GET | `/api/v1/expenses/summary` | RequireAuth | Aggregate totals/breakdowns for a period |
| Expenses | Compare | POST | `/api/v1/expenses/compare` | RequireAuth | Compare totals across two periods |
| Expenses | Get one | GET | `/api/v1/expenses/{expense_id}` | RequireAuth | Fetch a single expense |
| Expenses | Update | PATCH | `/api/v1/expenses/{expense_id}` | RequireAuth | Partial update of an expense |
| Expenses | Delete | DELETE | `/api/v1/expenses/{expense_id}` | RequireAuth | Delete an expense |
| Chat | Send message (REST) | POST | `/api/v1/chat` | RequireAuth | One-shot, non-streaming chat turn |
| Chat | Chat (streaming) | WS | `/api/v1/ws/chat/{session_id}` | RequireAuth | Streaming chat turn over WebSocket |
| Voice | Transcribe | POST | `/api/v1/voice/transcribe` | RequireAuth | Speech-to-text only |
| Voice | Respond | POST | `/api/v1/voice/respond` | RequireAuth | Speech-to-text → chat pipeline → text |
| Voice | Speak | POST | `/api/v1/voice/speak` | RequireAuth | Text-to-speech |
| Voice | Stop speaking | POST | `/api/v1/voice/speak/{operation_id}/stop` | RequireAuth | Cancel an in-progress `speak` |
| Voice | Get settings | GET | `/api/v1/voice/settings` | RequireAuth | Read language preferences + engine availability |
| Voice | Update settings | PUT | `/api/v1/voice/settings` | RequireAuth | Update language preferences |
| Media | Get state | GET | `/api/v1/media/state` | RequireAuth | Read last known playback state |
| Media | Media channel | WS | `/api/v1/ws/media/{client_id}` | RequireAuth | Bidirectional playback command/event channel |

**Not exposed as a client API** (verified absent — see §11 for detail):
Tasks, Workflows, Memory (read/write/search), Knowledge, Scheduler,
direct Tool/Provider invocation by id, Module registration, Metrics
(no `/metrics` endpoint).

---

## 6. API Reference

Conventions used below: `str?` = optional/nullable string, `= X` shows
the default when the field is omitted. All request/response models
are defined in `parika/api/schemas/*.py` and inherit `ApiModel`
(frozen, `extra="ignore"`).

### 6.1 Health / Status

#### `GET /api/v1/health`
- **Purpose:** basic reachability; answers the instant the ASGI app
  exists, before Core is constructed.
- **Auth:** none.
- **Response `200`:** `{"status": "ok"}`
- **Errors:** none possible.

#### `GET /api/v1/live`
- **Purpose:** event-loop liveness.
- **Auth:** none.
- **Response `200`:** `{"status": "ok"}`

#### `GET /api/v1/ready`
- **Purpose:** readiness — has `ParikaRuntime` finished constructing?
- **Auth:** none.
- **Response `200`:** `{"status": "ready"}` once `app.state.runtime`
  is set.
- **Response `503`:** `{"status": "starting"}` during the brief
  startup window.

#### `GET /api/v1/status`
- **Purpose:** the single authoritative snapshot of runtime state and
  system telemetry a client should poll for dashboards. Not itself a
  proof of any invocation capability.
- **Auth:** RequireAuth.
- **Request:** no parameters.
- **Response `200` — `StatusResponse`:**

| Field | Type | Notes |
|---|---|---|
| `uptime_seconds` | float | |
| `lifecycle_state` / `execution_state` / `interaction_state` | str | Core state-machine values |
| `overall_health` | str | |
| `active_modules` / `total_modules` | int | |
| `registered_capabilities` / `registered_tools` / `registered_providers` | int | |
| `providers` | list of `{id, enabled, available?, model_count}` | |
| `system` | object | `platform`, `operating_system`, `kernel_release?`, `architecture`, `hostname?` (redacted unless `[api].expose_hostname=true`), `boot_time?`, `uptime_seconds?`, `uptime_human?` |
| `cpu` | object | `usage_percent`, `logical_core_count`, `physical_core_count?`, `load_average_1m/5m/15m?` (Unix only), `current_frequency_mhz?` |
| `memory` | object | Host RAM (not PARIKA's Memory subsystem): `total_bytes`, `available_bytes`, `used_bytes`, `usage_percent`, `free_bytes?`, `swap_*?` |
| `gpu` | object | `detected`, `available`, `devices: []` (NVIDIA only; `{"detected": false, "available": false, "devices": []}` on any other host — never fails the request) |
| `temperature` | object | `available`, `sensors: []` (Linux only) |
| `storage` | object | PARIKA workspace filesystem only: `path`, `total_bytes`, `used_bytes`, `free_bytes`, `usage_percent` |
| `network` | object | `available`, `hostname?` (redacted), `bytes_sent?`, `bytes_received?`, `interfaces: []` (only if `[resources].network_interfaces_enabled`) |
| `parika` | object | `version`, `available_providers`, `total_models`, `memory_count`, `memory_storage_bytes`, `knowledge_engines`, `knowledge_sources` |
| `timestamp` | datetime | ISO 8601 UTC, when this snapshot was captured |

- **Every field the host cannot determine is `null`, never a
  fabricated `0`** — render as "N/A".
- **Recommended polling interval:**
  `[resources].recommended_client_poll_interval_seconds` in
  `config/defaults.toml` (default `5.0` seconds). PARIKA never pushes
  telemetry over WebSocket.
- **Example:**

```bash
curl http://127.0.0.1:2026/api/v1/status -H "X-API-Key: your-key"
```

```json
{
  "uptime_seconds": 42.1,
  "lifecycle_state": "running",
  "execution_state": "idle",
  "interaction_state": "idle",
  "overall_health": "healthy",
  "active_modules": 12,
  "total_modules": 12,
  "registered_capabilities": 38,
  "registered_tools": 14,
  "registered_providers": 3,
  "providers": [{"id": "provider.ollama", "enabled": true, "available": true, "model_count": 4}],
  "system": {"platform": "Linux", "architecture": "x86_64", "hostname": null},
  "cpu": {"usage_percent": 12.4, "logical_core_count": 16},
  "memory": {"total_bytes": 33285996544, "available_bytes": 20000000000, "used_bytes": 13285996544, "usage_percent": 39.9},
  "gpu": {"detected": false, "available": false, "devices": []},
  "temperature": {"available": true, "sensors": []},
  "storage": {"path": "/mnt/dev/python/parika", "total_bytes": 500000000000, "used_bytes": 100000000000, "free_bytes": 400000000000, "usage_percent": 20.0},
  "network": {"available": true, "hostname": null},
  "parika": {"version": "1.0.0", "available_providers": 3, "total_models": 4, "memory_count": 120, "memory_storage_bytes": 45000, "knowledge_engines": 1, "knowledge_sources": 3},
  "timestamp": "2026-08-10T06:00:00+00:00"
}
```

- **Errors:** only auth errors (§3) or 500 on unexpected failure.

---

### 6.2 Tools (discovery only)

#### `GET /api/v1/tools`
- **Purpose:** enumerate every registered Tool.
- **Auth:** RequireAuth.
- **Response `200` — `ToolsListResponse`:** `{"tools": [ToolSummary, ...]}`

`ToolSummary`: `id: str`, `name: str`, `version: str`,
`description: str`, `capabilities: [str]` (capability ids this Tool
can back), `enabled: bool`.

- **No direct `POST /tools/{id}/invoke` endpoint exists.** A Tool is
  reached over HTTP only through: (a) `POST
  /api/v1/capabilities/{id}/execute` when the tool backs a Tool
  category capability, (b) the two Voice endpoints with hard-coded
  tool ids, or (c) indirectly via `POST /api/v1/chat` /
  `WS /ws/chat/{session_id}`.

```bash
curl http://127.0.0.1:2026/api/v1/tools -H "X-API-Key: your-key"
```

```json
{"tools": [{"id": "tool.filesystem_read", "name": "Filesystem Read", "version": "1.0.0", "description": "Read a file from the workspace.", "capabilities": ["filesystem.read"], "enabled": true}]}
```

---

### 6.3 Modules

#### `GET /api/v1/modules`
- **Response `200` — `ModulesListResponse`:** `{"modules": [{"id", "version", "state"}]}`.
  `state` ∈ `active | inactive | failed | disabled`.

#### `POST /api/v1/modules/{module_id}/start`
- **Path param:** `module_id: str`.
- **Response `200` — `ModuleActionResponse`:** `{"module_id", "state"}`.
- **Errors:** `404` if unknown module id (`ModuleNotFoundError`);
  `409` if already active (`ModuleAlreadyLoadedError`).

#### `POST /api/v1/modules/{module_id}/stop`
- Same shape as `start`; loads/unloads the module's driver via
  `ModuleManager`.

```bash
curl -X POST http://127.0.0.1:2026/api/v1/modules/weather/stop -H "X-API-Key: your-key"
curl -X POST http://127.0.0.1:2026/api/v1/modules/weather/start -H "X-API-Key: your-key"
```

```json
{"module_id": "weather", "state": "active"}
```

A client cannot register/unregister a Module over HTTP — that is a
startup-time internal operation only.

---

### 6.4 Capabilities

#### `GET /api/v1/capabilities`
- **Response `200` — `CapabilitiesListResponse`:**
  `{"capabilities": [{"id", "name", "description", "category", "enabled"}]}`.
- `category` is one of the `CapabilityCategory` enum values (exact,
  as defined in code): `llm`, `embedding`, `vision`, `ocr`, `speech`,
  `translation`, `image_generation`, `video_generation`,
  `text_to_speech`, `memory`, `knowledge`, `tool`, `automation`,
  `workflow`, `reasoning`, `planning`, `retrieval`, `communication`,
  `filesystem`, `network`, `system`, `custom`.

#### `POST /api/v1/capabilities/{capability_id}/execute`
- **Purpose:** generic compatibility/fallback invocation for any
  registered capability that does not (yet) have its own dedicated
  endpoint — **prefer a domain-specific endpoint whenever one exists**
  (`/chat`, `/voice/*`, `/expenses/*`, `/modules/*`).
- **Path param:** `capability_id: str`.
- **Request body — `CapabilityExecuteRequestBody`:**

| Field | Type | Required | Default |
|---|---|---|---|
| `arguments` | `dict[str, Any]` | no | `{}` |
| `parameters` | `dict[str, Any]` | no | `{}` |

- **Response `200` — `CapabilityExecuteResponse`:** `{"capability_id", "result": Any, "attributes": dict}`
- **Behavior:** only works for **Tool-category** capabilities. The
  handler selects the lowest-`id`, enabled Tool whose `capabilities`
  list contains the requested capability id, then calls
  `ToolManager.execute()`. **Provider-backed capabilities (e.g.
  `chat.respond`) are not implemented via this endpoint and return
  `501`.**
- **Errors:** `404` unknown capability id (`CapabilityNotFoundError`);
  `501` provider-backed capability (`NotImplementedError`).

```bash
curl -X POST http://127.0.0.1:2026/api/v1/capabilities/filesystem.read/execute \
  -H "Content-Type: application/json" -H "X-API-Key: your-key" \
  -d '{"arguments": {"path": "README.md"}}'
```

```json
{"capability_id": "filesystem.read", "result": {"content": "..."}, "attributes": {}}
```

```python
import requests
r = requests.post(
    "http://127.0.0.1:2026/api/v1/capabilities/filesystem.read/execute",
    headers={"X-API-Key": "your-key"},
    json={"arguments": {"path": "README.md"}},
)
print(r.json())
```

---

### 6.5 Providers (discovery only)

#### `GET /api/v1/providers`
- **Response `200` — `ProvidersListResponse`:**
  `{"providers": [{"id", "name", "enabled", "state", "available?", "models": [{"id", "capabilities": []}]}]}`.
  `state` ∈ `disconnected | connecting | connected`.
- **There is no endpoint to connect, configure, or directly invoke a
  provider over HTTP.** Providers execute only through the chat
  pipeline (`Planner` selecting a provider+model) or are passively
  refreshed by `POST /api/v1/reload`.

```bash
curl http://127.0.0.1:2026/api/v1/providers -H "X-API-Key: your-key"
```

```json
{"providers": [{"id": "provider.ollama", "name": "Ollama", "enabled": true, "state": "connected", "available": true, "models": [{"id": "llama3.1:8b", "capabilities": ["llm"]}]}]}
```

---

### 6.6 Config

#### `GET /api/v1/config`
- **Query param:** `key: str?` — dotted config key (e.g.
  `application.name`); omit to get the entire merged Configuration.
- **Response `200` — `ConfigResponse`:** `{"key": str|null, "value": Any}`.
- **Read-only.** There is no `PUT`/`POST` config-write endpoint.

```bash
curl "http://127.0.0.1:2026/api/v1/config?key=application.name" -H "X-API-Key: your-key"
# {"key": "application.name", "value": "PARIKA"}
```

#### `POST /api/v1/reload`
- **Purpose:** unload+reload every currently active Module, then
  re-run model discovery and health refresh on every registered
  Provider.
- **Response `200` — `ReloadResponse`:**
  `{"reloaded_modules": [str], "reconnected_providers": [str], "failed_providers": [str]}`.

---

### 6.7 Expenses

Router prefix `/expenses`; the shared `ExpenseService` backs both this
API and the natural-language `expense.*` Tools used by chat (same
underlying data, two entry points). Amounts are always **strings**
on the wire (minor-unit-safe decimal formatting), never floats in
responses.

`ExpenseBody` (returned by every endpoint, nested or top-level):

| Field | Type | Nullable |
|---|---|---|
| `id` | str | no |
| `amount` | str | no |
| `currency` | str | no |
| `item` | str | no |
| `category` | str | yes |
| `expense_date` | str | no |
| `notes` | str | yes |
| `created_at` | str | no |
| `updated_at` | str | no |

#### `POST /api/v1/expenses` — create
- **Request — `ExpenseCreateRequestBody`:**

| Field | Type | Required | Default |
|---|---|---|---|
| `amount` | `float \| str` | **yes** | — |
| `item` | str | **yes** | — |
| `currency` | str? | no | server default (e.g. `INR`) |
| `category` | str? | no | `null` |
| `date` | str? | no | `"today"` if omitted; free-form date/period text accepted by `tools/expense/periods.py` |
| `notes` | str? | no | `null` |

- **Response `200` — `ExpenseMutationResponse`:** `{"expense": ExpenseBody}`.
- **Errors:** `422` missing `item`/`amount` (schema validation);
  `400` `ExpenseInvalidRequestError` (e.g. `amount <= 0`).

```bash
curl -X POST http://127.0.0.1:2026/api/v1/expenses \
  -H "Content-Type: application/json" -H "X-API-Key: your-key" \
  -d '{"amount": 2000, "item": "milk", "date": "today"}'
```
```json
{"expense": {"id": "exp_...", "amount": "2000.00", "currency": "INR", "item": "milk", "category": null, "expense_date": "2026-08-10", "notes": null, "created_at": "...", "updated_at": "..."}}
```

#### `GET /api/v1/expenses` — list
- **Query params (all optional):** `period: str`, `year: int`,
  `month: int`, `start_date: str`, `end_date: str`, `category: str`,
  `item: str`, `min_amount: float`, `max_amount: float`,
  `limit: int`, `offset: int = 0`.
- Valid `period` keywords (`tools/expense/periods.py`): `today`,
  `yesterday`, `this_week`, `last_week`, `this_month`, `last_month`,
  `this_year`, `last_year`, `first_half_month`, `second_half_month`,
  `custom` (requires both `start_date` and `end_date`).
- **Response `200` — `ExpenseListResponse`:** `{"expenses": [ExpenseBody], "count": int}`.

```bash
curl "http://127.0.0.1:2026/api/v1/expenses?period=today&item=unique-item" -H "X-API-Key: your-key"
```

#### `GET /api/v1/expenses/summary` — aggregate
- **Query params:** same filters as list, plus `largest_count: int?`.
- **Response `200` — `ExpenseSummaryResponse`:**
  `{"period_label", "currency", "total": str, "count": int, "by_category": {str: str}, "by_item": {str: str}, "by_date": {str: str}, "largest_expenses": [ExpenseBody]}`.

#### `POST /api/v1/expenses/compare`
- **Request — `ExpenseCompareRequestBody`:** `{"period_a": ExpensePeriodFilterBody, "period_b": ExpensePeriodFilterBody, "category": str?}`.
  `ExpensePeriodFilterBody`: `{"period"?, "year"?, "month"?, "start_date"?, "end_date"?, "category"?}` — both `period_a` and `period_b` are required top-level fields.
- **Response `200` — `ExpenseCompareResponse`:**
  `{"current": {"label", "total": str, "count": int}, "previous": {...}, "difference": str, "percentage_change": float|null, "direction": str, "note": str|null, "category_breakdown": {str: {str: str}}}`.
  `percentage_change` is `null` when the comparison-period total is
  zero (division by zero avoided, not an error).

```bash
curl -X POST http://127.0.0.1:2026/api/v1/expenses/compare \
  -H "Content-Type: application/json" -H "X-API-Key: your-key" \
  -d '{"period_a": {"period": "this_month"}, "period_b": {"period": "last_month"}}'
```

#### `GET /api/v1/expenses/{expense_id}` — fetch
- **Response `200` — `ExpenseMutationResponse`.** **Errors:** `404`
  `ExpenseNotFoundError`.

#### `PATCH /api/v1/expenses/{expense_id}` — partial update
- **Request — `ExpenseUpdateRequestBody`:** all fields optional
  (`amount`, `currency`, `item`, `category`, `date`, `notes`); only
  **explicitly sent** fields are applied (`exclude_unset` semantics —
  a field omitted from the JSON body is left unchanged; a field sent
  as `null` clears it, e.g. `{"category": null}`). `date` is renamed
  to `expense_date` server-side.
- **Response `200` — `ExpenseMutationResponse`.**

```bash
curl -X PATCH http://127.0.0.1:2026/api/v1/expenses/exp_123 \
  -H "Content-Type: application/json" -H "X-API-Key: your-key" \
  -d '{"category": null}'
```

#### `DELETE /api/v1/expenses/{expense_id}`
- **Response `200` — `ExpenseDeleteResponse`:** `{"removed": ExpenseBody}`.
- **Errors:** `404` if the id does not exist.

---

### 6.8 Chat

#### `POST /api/v1/chat` — non-streaming
- **Purpose:** the canonical single request/response shape all
  external clients use for a chat turn. Internally:
  `handle_chat()` → `InterfaceSession.submit_text()` → builds a Core
  `Goal`/`BrainRequest` → `Brain.handle()` (Planner → Routing Model →
  Tool/Provider execution).
- **Request — `ChatRequestBody`:**

| Field | Type | Required | Default |
|---|---|---|---|
| `text` | str | **yes** | — |
| `session_id` | str? | no | `null` (server generates a one-shot session, discarded after the reply) |

- **Response `200` — `ChatResponseBody`:**

| Field | Type | Nullable |
|---|---|---|
| `session_id` | str | no |
| `succeeded` | bool | no |
| `message` | str | yes (populated on success) |
| `error_message` | str | yes (populated on failure) |

- Pass the same `session_id` on subsequent calls to continue the same
  conversation context.
- **Errors:** `422` if `text` missing.

```javascript
const response = await fetch("http://127.0.0.1:2026/api/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": "your-key" },
    body: JSON.stringify({ text: "What is the weather?", session_id: "s-1" }),
});
const data = await response.json();
console.log(data.message);
```

```python
import requests
r = requests.post(
    "http://127.0.0.1:2026/api/v1/chat",
    headers={"X-API-Key": "your-key"},
    json={"text": "What is the weather?", "session_id": "s-1"},
)
print(r.json())
```

---

### 6.9 Voice

Six endpoints under `/voice`. Requires the optional `voice` extra
(`pip install -e ".[voice]"`) and `[providers.local_speech]` model
paths configured — with neither installed, endpoints respond with an
error rather than the server failing to start.

Audio is always transported as **base64 text inside the JSON body**,
never a multipart upload. There is **no MIME-type allowlist** — any
format the underlying `faster-whisper`/`ffmpeg` decoder accepts works
for input; output is always 16-bit mono PCM WAV
(`mime_type: "audio/wav"`).

**Language values:** input `"auto"` (default) / `"en"` / `"hi"`;
output `"en"` / `"hi"` / `"follow_input"`. Any other value → `422`.

#### `POST /api/v1/voice/transcribe` — speech-to-text only
- **Request — `VoiceTranscribeRequestBody`:** `{"audio_base64": str (required), "mime_type": str?, "language": str?}`.
- **Response `200` — `VoiceTranscribeResponseBody`:**
  `{"text", "language", "requested_input_language", "detected_input_language", "language_source"}` —
  `language_source` ∈ `"explicit" | "auto" | "unsupported"`.

#### `POST /api/v1/voice/respond` — audio → chat pipeline → text
- **Request — `VoiceRespondRequestBody`:** `{"audio_base64" (required), "mime_type"?, "language"?, "session_id"?}`.
- **Response `200` — `VoiceRespondResponseBody`:**
  `{"session_id", "succeeded", "transcript", "message", "error_message", "detected_input_language", "language_source"}`.
- **Never auto-speaks the reply** — this is the exact same
  `handle_chat()` pipeline `POST /chat` uses, just with speech-to-text
  in front of it. Calling `/voice/speak` afterward is an independent
  client decision.

#### `POST /api/v1/voice/speak` — text-to-speech
- **Request — `VoiceSpeakRequestBody`:** `{"text" (required), "voice"?, "language"?, "operation_id"?}`. Supply
  `operation_id` to make the operation cancellable via the stop
  endpoint below.
- **Response `200` — `VoiceSpeakResponseBody`:**
  `{"operation_id", "audio_base64", "mime_type": "audio/wav", "sample_rate", "cancelled": bool, "output_language"}`.
- Long text is synthesized in chunks (`[voice].tts_chunk_max_characters`,
  default 280); a concurrent stop request returns whatever audio was
  already produced with `"cancelled": true` — this is a **normal
  success response**, not an error.

#### `POST /api/v1/voice/speak/{operation_id}/stop`
- **Response `200` — `VoiceStopSpeakingResponseBody`:** `{"operation_id", "stopped": bool}`.
- Never errors on an unknown/already-completed id — just returns
  `"stopped": false`.

#### `GET /api/v1/voice/settings`
- **Response `200` — `VoiceSettingsResponseBody`:**
  `{"input_language", "output_language", "last_detected_input_language", "english_voice_configured", "hindi_voice_configured", "stt_available", "tts_available"}`.

#### `PUT /api/v1/voice/settings`
- **Request — `VoiceSettingsUpdateRequestBody`:** `{"input_language"?, "output_language"?}` — either field may be
  omitted to leave it unchanged. Changing settings never cancels an
  in-flight request; it affects only the *next* call.
- **Response `200`:** same shape as GET.

```bash
curl -X POST http://127.0.0.1:2026/api/v1/voice/speak \
  -H "Content-Type: application/json" -H "X-API-Key: your-key" \
  -d '{"text": "Hello there.", "operation_id": "speak-1"}'

curl -X POST http://127.0.0.1:2026/api/v1/voice/speak/speak-1/stop -H "X-API-Key: your-key"

curl -X PUT http://127.0.0.1:2026/api/v1/voice/settings \
  -H "Content-Type: application/json" -H "X-API-Key: your-key" \
  -d '{"input_language": "hi", "output_language": "hi"}'
```

---

### 6.10 Media

#### `GET /api/v1/media/state`
- **Purpose:** a plain REST read of PARIKA's last known playback
  state — mirrors the internal `media.get_state` Tool, with no
  side effects.
- **Response `200` — `MediaStateResponseBody`:**

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
  "updated_at": "2026-08-10T06:00:00+00:00"
}
```

`status` ∈ `idle | loading | playing | paused | stopped | buffering |
ended | error`. `client_connected` reflects whether any client is
connected over `WS /ws/media/{client_id}` right now — independent of
`status`.

See §10 for the full WebSocket protocol this state mirrors.

---

## 7. Shared Models

Base class for every request/response model: `ApiModel`
(`parika/api/schemas/common.py`) — `frozen=True`, `extra="ignore"`
(unrecognized fields from a client are silently ignored, never
rejected — the mechanism backing the additive-only stability policy).

| Model | Used by | Fields |
|---|---|---|
| `ExpenseBody` | all Expense endpoints | see §6.7 |
| `ExpensePeriodFilterBody` | `compare` | `period?`, `year?`, `month?`, `start_date?`, `end_date?`, `category?` |
| `MediaSourceBody` | `/media/state`, media WS | `type`, `url?`, `path?`, `media_id?`, `title?`, `artist?`, `album?`, `mime_type?`, `duration?` |
| `ToolSummary` | `/tools` | `id`, `name`, `version`, `description`, `capabilities: [str]`, `enabled` |
| `ModuleSummary` | `/modules` | `id`, `version`, `state` |
| `CapabilitySummary` | `/capabilities` | `id`, `name`, `description`, `category`, `enabled` |
| `ProviderSummary` / `ProviderModelSummary` | `/providers` | see §6.5 |

`MediaSourceBody.type` values and which fields are populated for each:

| `type` | Populated fields |
|---|---|
| `"youtube"` | `url`, `media_id`, `title` |
| `"local"` | `path`, `title`, `mime_type` (server-filesystem path; never directly usable as a browser `src` — see `docs/guides/Running.md` §12.3 "Local files") |
| `"direct_url"` | `url`, `mime_type` |
| `"stream"` | `url` (e.g. HLS `.m3u8`) |

---

## 8. Errors

**Single centralized error envelope** (`parika/api/errors.py`),
applied uniformly to every route:

```json
{
  "error": {
    "type": "ExpenseNotFoundError",
    "message": "No expense found with id 'exp_999'.",
    "request_id": "a1b2c3d4e5f6..."
  }
}
```

- `type`: the raised exception's Python class name (unmodified —
  Core exceptions are never renamed or wrapped for the API layer).
- `message`: `str(exception)`, or the HTTP status phrase if empty.
- `request_id`: a fresh `uuid4().hex` per error response, for
  correlating with server logs.

### Status code mapping (exact, from `parika/api/errors.py`)

| Exception class-name suffix | HTTP status |
|---|---|
| `NotFoundError` | 404 |
| `AlreadyRegisteredError`, `AlreadyLoadedError`, `AlreadyExistsError`, `DisabledError`, `NotLoadedError`, `AmbiguousMatchError` | 409 |
| `PermissionError`, `PermissionDeniedError` | 403 |
| `InvalidCredentialsError`, `ExpiredTokenError`, `MissingCredentialsError`, `UnauthorizedError` | 401 |
| `InvalidError`, `InvalidRequestError` | 400 |
| `NotImplementedError` (exact type, not suffix) | 501 |
| Request body/query fails Pydantic validation | 422 (`RequestValidationError`) |
| Anything else | 500 |

Classification is by **class name suffix**, not an explicit
`isinstance` list — a new Core `*NotFoundError` anywhere in the
codebase is automatically mapped without any API-layer code change.

**Caveat:** FastAPI's default `HTTPException` handler is **not**
overridden. If any code path ever raises a raw `HTTPException`
(none do today), it returns Starlette's built-in `{"detail": ...}`
shape instead of the `{"error": ...}` envelope above.

### Known concrete error types (non-exhaustive; per suffix mapping)

| Error | Status | Raised by |
|---|---|---|
| `ModuleNotFoundError` | 404 | `POST /modules/{id}/start\|stop` with unknown id |
| `ModuleAlreadyLoadedError` | 409 | starting an already-active module |
| `CapabilityNotFoundError` | 404 | `POST /capabilities/{id}/execute` with unknown id |
| `ExpenseNotFoundError` | 404 | expense GET/PATCH/DELETE with unknown id |
| `ExpenseInvalidRequestError` | 400 | e.g. `amount <= 0`, invalid `custom` period missing dates |
| `ExpenseAmbiguousMatchError` | 409 | a description-based match resolves to more than one record |
| `MissingCredentialsError` / `InvalidCredentialsError` / `ExpiredTokenError` | 401 | auth failures (§3) |
| `NotImplementedError` | 501 | e.g. provider-backed capability via the generic execute endpoint |

---

## 9. Streaming — `WS /api/v1/ws/chat/{session_id}`

- **Auth:** `Authorization: Bearer`, `X-API-Key`, or `?token=` query
  param (§3). On failure, the socket is **closed with code 1008**
  before `accept()`.
- **Path param:** `session_id` — caller-chosen conversation id
  (reused across turns to keep context).

**Client → server**, one JSON frame per turn:
```json
{"type": "message", "text": "Hello"}
```
(Empty `text` is silently ignored — no frame sent back.)

**Server → client**, per turn:
```json
{"type": "token", "content": "..."}      // zero or more
{"type": "done", "done": true, "response": {"session_id": "...", "succeeded": true, "message": "...", "error_message": null}}  // exactly one, terminal
```

On an in-turn failure:
```json
{"type": "error", "message": "..."}
```
(the connection stays open for the next turn).

**Known limitation (documented in code,
`parika/api/ws/chat.py`):** token fragments are currently **buffered
and delivered all at once after the turn completes**, not truly
interleaved with generation — a SQLite `check_same_thread=True`
constraint on the session store forces `handle_chat()` to run
synchronously on the connection's own event-loop task. True
token-by-token streaming is a tracked follow-up, not yet shipped.
A client should not assume real-time token arrival timing.

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect(
        "ws://127.0.0.1:2026/api/v1/ws/chat/my-session?token=your-key"
    ) as ws:
        await ws.send(json.dumps({"text": "Hello"}))
        while True:
            message = json.loads(await ws.recv())
            print(message)
            if message["type"] == "done":
                break

asyncio.run(main())
```

There is **no SSE endpoint** anywhere in PARIKA. Streaming is
WebSocket-only.

---

## 10. Events — `WS /api/v1/ws/media/{client_id}`

- **Auth:** identical mechanics to the chat WebSocket (§9); close
  code 1008 on failure.
- **Path param:** `client_id` — caller-chosen identifier for this
  connection (e.g. a browser tab id); unrelated to any chat
  `session_id`.
- **Handshake requirement:** a connection must send `{"type":
  "media.ready"}` before it will receive any dispatched command.
  Connecting alone only marks `MediaState.client_connected = true`;
  it does not mark the connection dispatch-ready.

**Server → client** (commands, fire-and-forget, never blocks the rest
of PARIKA's request processing):
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

**Client → server** (events, applied to `MediaState`):
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

- **Unknown inbound `type`:** the server replies `{"type": "error",
  "message": "Unknown media event type '<type>'."}` on the same
  socket **without disconnecting**.
- **Multiple simultaneous ready connections** all receive every
  dispatched command — PARIKA does not arbitrate "who is
  authoritative" among them.
- **Dispatching a command is not proof of playback.** The Web Client
  must report back (`media.play_started`/`media.error`/
  `media.state_changed`) for `GET /api/v1/media/state` to reflect
  reality.

```python
import asyncio, websockets

async def main():
    async with websockets.connect(
        "ws://127.0.0.1:2026/api/v1/ws/media/my-web-client?token=your-key"
    ) as ws:
        await ws.send('{"type": "media.ready"}')
        async for raw in ws:
            print("command from PARIKA:", raw)
            # await ws.send('{"type": "media.play_started"}')

asyncio.run(main())
```

Full source-type/resolution/local-file/security detail lives in
`docs/guides/Running.md` §12.3 ("Media API") and ADR 0004 — this
section covers the wire protocol only.

---

## 11. Client Workflows

### 11.1 Authenticate → call a protected API

```bash
# api_key mode
curl http://127.0.0.1:2026/api/v1/status -H "X-API-Key: your-plaintext-key"
```
```python
import requests
requests.get("http://127.0.0.1:2026/api/v1/status", headers={"X-API-Key": "your-key"})
```

### 11.2 Discover a capability → invoke it (generic fallback)

```
GET /api/v1/capabilities                              -> find "filesystem.read", category "filesystem"
POST /api/v1/capabilities/filesystem.read/execute      -> {"arguments": {"path": "README.md"}}
```
If the capability is provider-backed (e.g. `chat.respond`), this
fallback returns `501` — use `POST /api/v1/chat` instead.

### 11.3 Chat turn, non-streaming, with session continuity

```
POST /api/v1/chat {"text": "Remember my name is Alex"}     -> session_id: "s-1"
POST /api/v1/chat {"text": "What's my name?", "session_id": "s-1"}
```

### 11.4 Chat turn, streaming

```
WS /api/v1/ws/chat/{session_id}
  -> send {"type": "message", "text": "..."}
  <- receive zero or more {"type": "token", ...} (currently delivered together, see §9)
  <- receive exactly one {"type": "done", "response": {...}}
```

### 11.5 Voice round-trip (speak-in, speak-out)

```
POST /api/v1/voice/respond {"audio_base64": "<b64 wav>"}
  -> {"transcript": "...", "message": "...", "succeeded": true}
POST /api/v1/voice/speak {"text": "<message from above>", "operation_id": "op-1"}
  -> {"audio_base64": "<b64 wav>", "mime_type": "audio/wav"}
# optionally, while speak is still in progress:
POST /api/v1/voice/speak/op-1/stop
```

### 11.6 Media playback via chat + a connected Web Client

```
1. Web Client connects: WS /api/v1/ws/media/my-client, sends {"type": "media.ready"}
2. User: POST /api/v1/chat {"text": "Play Imagine Dragons Believer"}
   -> internally calls media.play Tool -> dispatches
      {"type": "media.play", "payload": {"source": {...}}} to the ready connection
3. Web Client plays it, reports {"type": "media.play_started"}
4. Any client can poll GET /api/v1/media/state to render current status/position
```

### 11.7 Expense management end-to-end

```
POST /api/v1/expenses {"amount": 250, "item": "coffee", "category": "Food"}
GET  /api/v1/expenses?period=this_month
GET  /api/v1/expenses/summary?period=this_month
POST /api/v1/expenses/compare {"period_a": {"period": "this_month"}, "period_b": {"period": "last_month"}}
PATCH /api/v1/expenses/{id} {"category": "Dining"}
DELETE /api/v1/expenses/{id}
```

### 11.8 Config inspection + operational reload

```
GET  /api/v1/config?key=application.name
POST /api/v1/reload      # after editing config/*.toml and wanting Modules/Providers refreshed without a full restart
```

---

## 12. Client Integration Checklist

- [ ] Determine your deployment's actual `host:port` — do not hardcode
      `127.0.0.1:2026`; read it from your own client configuration.
- [ ] Confirm `[api.auth].mode` for your deployment and implement the
      matching credential (none / `X-API-Key` or `Authorization:
      Bearer` / JWT bearer). For WebSockets, be ready to use
      `?token=` if you cannot set headers.
- [ ] Send `Content-Type: application/json` on every request with a
      body.
- [ ] Treat every response as a flat JSON object per its documented
      schema — there is no `{"data": ...}` envelope to unwrap.
- [ ] Parse errors as `{"error": {"type", "message", "request_id"}}`
      and branch on `type`/HTTP status, not on message text.
- [ ] Never assume a status code beyond those documented per endpoint
      in §6/§8; treat unexpected extra fields in any response as
      forward-compatible additions to ignore.
- [ ] For chat: reuse a stable `session_id` across turns you want
      connected; treat `succeeded: false` + `error_message` as the
      normal way a turn reports failure (HTTP status is still `200`
      in that case — check `succeeded`, not just the status code).
- [ ] For the chat/media WebSockets: implement the close-code-1008
      auth-failure path distinctly from an in-band `{"type": "error"}`
      frame.
- [ ] For Voice: do not assume any particular audio MIME type is
      required for input; always read `mime_type`/`audio/wav` on
      output responses rather than assuming.
- [ ] For Media: send `{"type": "media.ready"}` only once your own
      player can actually accept a command, and always report back
      real playback state — PARIKA's `GET /api/v1/media/state` is
      only as accurate as your own event reporting.
- [ ] Poll `GET /api/v1/status` at or below
      `resources.recommended_client_poll_interval_seconds` (default
      5s) — PARIKA does not push telemetry.
- [ ] Do not depend on capability/tool ids, `CapabilityCategory`
      values, or error `type` names being anything other than exactly
      what §5/§6/§8 document — they are stable strings defined in
      Core, not free-form.
- [ ] Do not build against Tasks, Workflows, Memory, Knowledge, or
      Scheduler HTTP endpoints — none exist (see §13).

---

## 13. Explicitly Not Exposed (verified absent, not merely undocumented)

These architectural components exist internally in `parika/core/` but
have **no HTTP/WebSocket route at all** — confirmed by repository-wide
search across `parika/api/`. Do not build a client integration
assuming any of the following exist:

| Component | Internal location | Reachable by a client? |
|---|---|---|
| **Tasks** (creation/status/poll/cancel) | `parika/core/task_manager/` | No — used only inside `Brain.handle()` |
| **Workflows** | `parika/core/workflow_engine/` | No — and its execution core (`_create_execution`/`_execute_step`) is itself `NotImplementedError` today, unrelated to the API layer |
| **Memory** (read/write/search) | `parika/core/memory_manager/`, `parika/modules/memory/` | No direct API — only reachable via natural language through `/chat`; `GET /status` exposes only aggregate counts (`memory_count`, `memory_storage_bytes`) |
| **Knowledge** | `parika/core/knowledge_manager/` | No direct API — same pattern as Memory; `GET /status` exposes only aggregate counts |
| **Scheduler** | `parika/core/scheduler/` | No — in-process timer only |
| **Metrics** | `parika/core/metrics_manager/` | No `/metrics` endpoint; no Prometheus/OpenTelemetry exporter anywhere |
| **Direct Tool invocation by id** | `parika/core/tool_manager/` | No `POST /tools/{id}/invoke` — only via the generic capability-execute fallback, the two Voice endpoints, or chat |
| **Direct Provider invocation/configuration** | `parika/core/provider_manager/` | No — list-only (`GET /providers`); execution happens only inside the chat pipeline |
| **Module registration** (as opposed to start/stop) | `parika/core/module_manager/` | No — registration is startup-time internal only |
| **Login / token-issuance endpoint** | `parika/api/auth/` | No — API keys/JWTs are provisioned out-of-band by an operator, never issued over HTTP |

If a future client genuinely needs one of these, it requires a new,
explicitly designed endpoint — not an assumption that an internal
manager's method is already reachable.
