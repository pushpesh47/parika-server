# ADR 0003: Expense Management (`expense.*` Capabilities/Tools + `/api/v1/expenses...`)

## Context

PARIKA's operator currently tracks personal expenses manually in a
spreadsheet (Day / Date / Item / Price, with manually-computed daily,
first-half, second-half, and monthly totals). The requirement is to
replace that manual process with a native PARIKA capability: the
operator should be able to say "add rs 2000 for milk today" and have
PARIKA store, retrieve, modify, remove, summarize, and compare
expenses through the existing Planner/Brain/Tool pipeline, plus a
structured Web Client surface for the same data.

The architecture is frozen: `ServiceContainer`, `CapabilityRegistry`,
`ToolManager`, `ModuleManager`, `Planner`, `Brain`, `Router`, and the
API layer's dispatch pattern (`requests.py` -> `router_bindings.py`
-> `handlers/`) each already have a defined shape (see
`docs/development/{Module_Guide,Tool_Guide}.md` and
`docs/architecture/Request_Understanding.md`). PARIKA has no existing
Decimal/exact-money convention (the Currency Tool uses `float`), no
shared natural-language date-parsing utility, and no Web Client at
all yet - only `parika/console/` (CLI) and the REST/WebSocket API
exist as Interfaces today.

## Decision

1. **A native Module/Tool pair, following the Weather/Currency
   shape - not a standalone application.** `parika/modules/expense/`
   (manifest + `ExpenseModuleDriver`, registration/lifecycle only) and
   `parika/tools/expense/` (domain model, SQLite storage, deterministic
   calculations, and the `ExpenseToolDriver`) mirror the existing
   Currency Module's package layout exactly. Seven Capabilities
   (`expense.add_expense`, `get_expense`, `list_expenses`,
   `update_expense`, `remove_expense`, `summarize_expenses`,
   `compare_periods`) are each registered as their own Tool
   (`tool.expense_*`), per the existing "one Tool per Capability" rule
   (`docs/development/Tool_Guide.md` section 21) - `ToolRequest` carries
   no capability id, so one multi-capability Tool could not tell which
   operation a call targeted.

2. **Expenses are structured domain data, not conversational Memory.**
   `ExpenseStorage` owns a dedicated `data/expense.sqlite3` database
   (its own table, its own schema-version metadata row), following the
   exact same `sqlite3`/WAL/schema-versioning pattern as
   `ExperienceStorage`/`MemoryStorage`. `MemoryManager`/
   `KnowledgeManager` are never involved in storing an expense itself -
   they remain reserved for genuinely conversational/preference
   context (e.g. "I usually categorize milk as groceries"), which this
   module deliberately does not implement (see Decision 8).

3. **Deterministic calculation, never LLM calculation.** Every total,
   category/item/date/month aggregate, and period comparison is
   computed by `ExpenseStorage`'s SQL `SUM`/`GROUP BY` over an exact
   integer `amount_minor` column, composed by
   `ExpenseService`/`calculations.py` - never by asking a model to add
   up retrieved text. The Planner/model only ever decides *which*
   Capability/filter to call; `ExpenseService` performs the actual
   arithmetic.

4. **Exact money representation: integer minor units, never a
   `float`.** Every persisted and aggregated amount is an integer
   number of minor units (paise/cents; `parika/tools/expense/money.py`).
   This is a deliberate divergence from the Currency Tool's existing
   `float` convention (acceptable there for a live, inherently
   imprecise exchange rate; unacceptable here, where "why is my total
   off by a paise" would be a real, reportable bug). `Decimal` is used
   only at the boundary (parsing a caller-supplied amount, formatting a
   result); `str()` (never `float()`) is used for every amount in every
   Tool/API response, so a JSON client never reintroduces
   floating-point error into an exactly-computed value. `percentage_change`
   in a period comparison is the one place `float` appears, since a
   percentage is inherently a display ratio, never a persisted or
   compared monetary value.

5. **`expense_date` is deliberately distinct from `created_at`.**
   `Expense.expense_date` is when the expense occurred (resolved from
   the user's request, defaulting to today when omitted);
   `Expense.created_at` is always `now()` at insert time and is never
   used as a substitute. Updating an expense's date only ever changes
   `expense_date` and `updated_at` - `created_at` is immutable for the
   life of the record.

6. **One shared `ExpenseService`, reached two ways - never two data
   paths.** `ExpenseService` (wrapping `ExpenseStorage`) is
   constructed exactly once, at the composition root
   (`parika/interfaces/runtime.py`), exactly like
   `TtsOperationRegistry`/`VoiceLanguagePreferenceStore` are for Voice.
   The natural-language path (`ExpenseToolDriver`, reached via
   Planner's existing native-tool-calling mechanism - see
   `docs/architecture/Request_Understanding.md` section 4) and the
   direct, structured `/api/v1/expenses...` endpoints (the Web
   Client's CRUD/dashboard surface) both call this one instance -
   reached from the API layer through `ServiceContainer`, exactly like
   the Voice API's settings endpoints already do. A record added by
   voice/chat is immediately visible to the Web Client and vice versa;
   there is no second, competing storage or reasoning path.

   The direct API handlers call `ExpenseService` *directly*, not
   through `ToolManager.execute()`: `ToolManager` uniformly wraps every
   exception into a generic `ToolExecutionError`
   (`parika/core/tool_manager/tool_manager.py`), which would collapse
   `ExpenseNotFoundError`/`ExpenseInvalidRequestError`/
   `ExpenseAmbiguousMatchError` into an indistinguishable HTTP 500 for
   every structured API caller. Calling the service directly lets the
   original exception's class name reach `parika/api/errors.py`'s
   existing suffix-matching table unmodified, except for one additive
   entry (`"AmbiguousMatchError"` -> 409) that table gains for
   `ExpenseAmbiguousMatchError` - the smallest possible extension of an
   already-generic, class-name-based mapping table, not a redesign of
   it.

7. **The Web Client is the plain static HTML5/CSS/JavaScript bundle
   ADR 0001 already anticipated, not a new frontend architecture.**
   `web/index.html`/`app.js`/`styles.css` is a small, dependency-free,
   build-step-free bundle. It calls `/api/v1/chat` (unmodified) for
   natural-language quick-add, and the new direct `/api/v1/expenses...`
   endpoints for the dashboard/list/filter/add/edit/delete/compare
   views - it never re-implements PARIKA's natural-language
   understanding itself. `parika/server/app.py` additionally mounts it
   at `/app` for convenience (`fastapi.staticfiles.StaticFiles`,
   already a FastAPI/Starlette dependency - no new package), but the
   bundle is an ordinary static site that could equally be served from
   any other origin, which is exactly why `[api.cors]` already exists.

8. **Category inference is advisory and non-destructive; `Investment`
   is a category, not a new transaction type.** `Expense.category` is
   a free string (never a validated enum); `[expense].categories`
   supplies a suggested vocabulary (Food, Groceries, Medicine,
   Transport, Shopping, Bills, Education, Investment, Personal,
   Household, Other) advertised to the model via the Tool Affordance
   Contract, but the original `item`/description is always stored
   verbatim regardless of what category (if any) is inferred, and an
   uncertain/omitted category is stored as `None` rather than guessed.
   A SIP-like entry is tracked with `category="Investment"` like any
   other expense; PARIKA does not introduce a second transaction-type
   field, double-entry accounting, or any other accounting semantics
   to distinguish it - see "Alternatives Considered" and "Intentionally
   Deferred" below.

9. **Match-based update/delete never silently touches the wrong
   record.** A natural-language request with no explicit id ("remove
   the milk expense", "delete the 2000 expense") resolves candidates
   via `ExpenseService.find_matches()`. Zero matches raises
   `ExpenseNotFoundError`; more than one match raises
   `ExpenseAmbiguousMatchError` (carrying every candidate) and changes
   nothing. `ExpenseToolDriver` catches both directly for the
   Tool-calling path and returns a normal, non-error
   `ToolResponse` (`{"status": "ambiguous", "candidates": [...]}` /
   `{"status": "not_found", ...}`) rather than an execution failure,
   so the model can present the candidates and ask the user to
   clarify - a legitimate, informative outcome, not a bug. Bulk
   deletion only ever happens when the caller explicitly passes
   `confirm_bulk_delete: true`. The direct, structured API never
   exercises this path at all: the Web Client always already knows a
   specific `expense_id` (it lists expenses, with their ids, before
   ever editing/deleting one), so `PATCH`/`DELETE
   /api/v1/expenses/{id}` only ever raises `ExpenseNotFoundError` (404)
   for an unknown id.

10. **Period semantics, defined once, deterministically
    (`parika/tools/expense/periods.py`).** A week is Monday-Sunday.
    "First half of a month" is day 1 through day 15 (inclusive);
    "second half" is day 16 through the month's last day (inclusive).
    `resolve_period()` is the single function every
    list/summarize/compare Capability calls for every period keyword
    (`today`, `yesterday`, `this_week`, `last_week`, `this_month`,
    `last_month`, `this_year`, `last_year`, `first_half_month`,
    `second_half_month`, `custom`); no Capability re-derives period
    boundaries itself.

11. **Deterministic date-phrase resolution
    (`parika/tools/expense/dates.py`), because no shared PARIKA date
    utility exists yet.** `parse_expense_date()` is one small, fully
    unit-tested, ordered set of parsing strategies (relative keywords,
    weekday names, ISO, `DD/MM/YYYY`, `<day> <month name>[, year]`) -
    not a scattered pile of ad hoc string hacks, and not a second
    natural-language reasoning path: the model still decides *what*
    date phrase to extract from a user's sentence (e.g. "yesterday",
    "5 August") via its own native tool-calling; this module only
    resolves that already-extracted phrase into one concrete `date`
    deterministically. See "Alternatives Considered" for why this was
    not promoted into a new shared Core utility.

12. **Three domain events, and no more.** `expense.created`/
    `expense.updated`/`expense.deleted`
    (`parika/tools/expense/events.py`) are published via the existing,
    unmodified `EventBus` after every successful mutation, following
    `<component>.<action>` naming. Expense Management never subscribes
    to its own events; they exist solely so a future module (e.g. a
    notification or budgeting module) could observe expense activity
    without coupling to this module's internals - introduced because
    they are genuinely useful integration points, not merely because
    they were technically possible.

## Alternatives Considered

- **Storing amounts as `float`, matching the Currency Tool.**
  Rejected: the requirement is explicit that persisted monetary values
  and financial totals must never use binary floating point. Integer
  minor units were chosen over `Decimal`-as-storage for the same
  reason `ExperienceStorage`/`MemoryStorage` store everything as
  primitive SQLite columns: SQLite has no native arbitrary-precision
  decimal type, and integer `SUM()` is both exact and fully supported
  by SQL aggregation.
- **A full double-entry accounting subsystem, or a distinct
  "transaction type" field, to special-case investments (e.g. SIP).**
  Rejected as over-engineering for this module's scope. `category`
  already provides enough separation (`Investment` vs. every other
  category) for the requirement's own examples; introducing
  transaction types/double-entry accounting would be a disproportionate
  new subsystem for a "personal expense tracker" requirement that
  explicitly forbids over-engineering. Deferred to a possible future,
  dedicated financial module (see "Intentionally Deferred" below).
- **Promoting `dates.py`/`periods.py` into a new shared Core
  component (e.g. a `DateResolver` Core service).** Rejected for this
  increment: no other existing module currently needs natural-language
  date resolution, so generalizing now would be speculative Core
  surface added without a second real consumer. The functions are
  written as small, pure, dependency-free modules specifically so they
  *could* be lifted into Core later with no API change if a second
  module needs them - this ADR documents that as the trigger condition,
  not something to build preemptively.
- **A JavaScript framework/build pipeline for the Web Client (React,
  Vue, a bundler).** Rejected: ADR 0001 already describes the intended
  Web Client as "a pure HTML5/CSS/JavaScript presentation layer", and
  the requirement explicitly says not to introduce a large charting
  framework "merely for this module". The dashboard's category/trend/
  largest-expense visualizations are plain CSS bar rows computed from
  already-deterministic totals, not a charting library.
- **Raising `ExpenseAmbiguousMatchError`/`ExpenseNotFoundError` as Tool
  execution failures for match-based update/delete.** Rejected for the
  Tool-calling path: `ToolManager` would wrap either into a generic
  `ToolExecutionError`, and the chat pipeline's `ToolCallResolver`
  would serialize that into an opaque `{"error": "..."}` string for
  the model - losing the actual candidate list a user needs to see to
  disambiguate. Returning a normal `ToolResponse` with a `"status"`
  field instead lets the model relay the candidates naturally. (The
  direct API still raises them as exceptions, mapped by
  `parika/api/errors.py`, since that surface never exercises the
  match-based path at all - see Decision 9.)
- **Per-user data ownership / a new authentication mechanism scoped to
  "whose expenses are these".** Investigated and explicitly *not*
  implemented - see "Architectural Gap Identified" below.

## Architectural Gap Identified (Not Fixed by This Change)

PARIKA has no multi-user/per-account concept anywhere today:
`AuthContext.subject` is an opaque authenticated-caller identifier
that no handler in the codebase currently consults, and
`PermissionManager`/`WorkspacePermissionManager` are workspace-path-
scoped, not user-scoped (ADR 0002 already documents this stance: "PARIKA
has no multi-tenant/per-account preference concept today \[...] it is a
personal assistant, single operator"). The requirement's "do not
expose another user's expenses" is therefore satisfied only in the
sense that Expense Management inherits PARIKA's existing, single-
operator security model unchanged (the same `RequireAuth`/
`AuthContext` gate every other endpoint already uses) - it does not,
and cannot, add per-user row-level isolation, because there is no user
model to isolate by. Introducing one would be a Core-wide identity
change far larger than this module's scope, and is explicitly not
attempted here. If/when PARIKA introduces multi-user accounts, the
natural seam is already visible: `AuthContext.subject` would become a
real user id, threaded into `ExpenseStorage`'s schema as an `owner_id`
column and into `ExpenseFilter`.

## Intentionally Deferred

- **CSV/XLSX spreadsheet import/export** (the operator's original
  Day/Date/Item/Price spreadsheet format). Not implemented now. The
  domain model (`Expense`) and storage layer are already shaped to
  make a small, additive import Tool straightforward later (parse
  rows -> `ExpenseService.create()` per row), but building a general
  spreadsheet-import subsystem now would exceed this increment's
  scope, per the requirement's own explicit caution against expanding
  it unnecessarily.
- **Bank sync/integration, budgeting, financial forecasting, debt/loan
  management, recurring transactions, receipt OCR, external financial
  APIs.** Explicitly out of scope per the requirement; none of the
  above was implemented or partially scaffolded.
- **Per-user data isolation.** See "Architectural Gap Identified"
  above.
- **Multi-currency-aware comparisons** (e.g. comparing a INR total
  against a USD total with live conversion). `currency` is stored per
  expense and `[expense].default_currency` governs new expenses with
  no explicit currency, but `summarize`/`compare` do not currently
  convert or separate multiple currencies - acceptable for this
  single-operator, INR-default personal tracker, and a natural future
  extension point (the existing, separate Currency Tool already
  provides `currency.convert`) rather than something this module
  should re-implement.

## Consequences

- New files: `parika/modules/expense/{__init__,manifest,driver}.py`;
  `parika/tools/expense/{__init__,exceptions,money,dates,periods,
  model,filters,storage,calculations,events,config,manifest,
  service,driver}.py`; `parika/api/{schemas,handlers}/expense.py`,
  `parika/api/routers/expense.py`; `web/{index.html,app.js,styles.css}`;
  this ADR.
- Modified files: `parika/interfaces/runtime.py` (module
  registration, `ExpenseService`/`ExpenseStorage` construction, one new
  `ServiceContainer` entry), `parika/api/{requests,router_bindings,
  errors}.py` and `parika/api/routers/__init__.py` (seven new routes,
  one additive suffix-table entry), `parika/server/app.py` (one
  additive static-file mount), `config/defaults.toml` (new `[expense]`
  section). No existing Core component's public behavior changed; the
  three pre-existing tests that hardcoded the exact built-in
  module/route count were updated to include the new module/routes,
  exactly as they were each time a previous Module was added.
- A new SQLite database file, `data/expense.sqlite3`, is created on
  first run, following the exact same pattern as
  `data/{memory,knowledge,experience}.sqlite3`.
- The full test suite (3083 tests as of this change, including the new
  Expense Management unit/module/API tests below) passes.
