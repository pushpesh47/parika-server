
# PARIKA Capability Guide

**Status:** Authoritative guide for defining and registering PARIKA Capabilities.

> This document replaces **Capability_Development_Guide.md** as the single source of truth for Capability development.

---

# 1. Purpose

**When to read this:** use this guide when defining a new capability or updating an existing capability registration.

**Related documents:** [../architecture/PARIKA_Architecture_Specification_v1.0.md](../architecture/PARIKA_Architecture_Specification_v1.0.md), [../architecture/Core_Component_Responsibilities.md](../architecture/Core_Component_Responsibilities.md), and [Module_Guide.md](Module_Guide.md).

A Capability represents **what PARIKA can do**, not **how it is implemented**.

A Capability:

- has a unique identifier
- belongs to a category
- is registered in CapabilityRegistry
- is implemented by either a Tool or a Provider

---

# 2. Architecture

A Capability consists of immutable metadata.

Typical fields:

- id
- name
- description
- category
- version
- provider
- source
- tags
- enabled
- metadata

CapabilityRegistry is the authoritative registry.

Capabilities never execute work themselves.

---

# 3. Capability Categories

Choose the correct category because it determines execution.

Typical categories include:

- TOOL
- LLM
- REASONING
- EMBEDDING
- VISION
- OCR
- SPEECH
- TRANSLATION
- MEMORY
- KNOWLEDGE
- AUTOMATION
- WORKFLOW
- RETRIEVAL
- COMMUNICATION
- FILESYSTEM
- NETWORK
- SYSTEM
- CUSTOM

Use TOOL for deterministic execution.

Use AI categories only when model inference is required.

---

# 4. Registration

Register Capabilities during Module startup.

Typical operations:

- register()
- enable()
- disable()
- unregister()

Never register at import time.

---

# 5. Lifecycle

Capabilities have only two runtime concepts:

```text
Registered
    ↓
Enabled / Disabled
```

Disable temporarily.

Unregister only when permanently removing the Capability.

---

# 6. Resolution

CapabilityResolver:

- validates existence
- validates enabled state
- returns CapabilityResolution

It never:

- executes work
- selects Providers
- selects Tools
- evaluates Policies

---

# 7. Execution Flow

This is the Capability-centric view: where a Capability id is resolved,
gated, and finally backed by a Tool or a Provider. See
[`../architecture/PARIKA_Decision_Flow.md`](../architecture/PARIKA_Decision_Flow.md)
§1 for the complete, verified pipeline diagram (including TaskManager
and CapabilityExecutor) — this is a deliberately narrower view, not a
competing one.

```text
Brain
    ↓
Planner
    ↓
CapabilityResolver
    ↓
Policy / Resources
    ↓
ToolManager or ProviderManager
    ↓
ToolDriver / ProviderDriver
    ↓
Result
```

Capabilities are identifiers that flow through every execution layer.

---

# 8. Validation

Two validation stages exist:

1. Registration validation
2. Resolution validation

Availability of a Tool or Provider is checked later during planning.

---

# 9. Dependencies

Capabilities should remain independent.

Workflow dependencies belong at the Goal level rather than inside Capability definitions.

---

# 10. Versioning

Version is descriptive metadata.

Breaking changes should use a new Capability id rather than replacing an existing definition.

---

# 11. Naming

Recommended format:

```text
domain.action

Examples

web.search
chat.answer
filesystem.read
git.commit
pdf.extract_text
```

Use lowercase with dot-separated names.

---

# 12. Best Practices

- One clear responsibility.
- One appropriate category.
- Register from a single Module.
- Keep tags consistent.
- Register implementation together with Capability.
- Disable instead of unregistering whenever possible.

---

# 13. Common Mistakes

- Choosing the wrong category.
- Registering duplicate ids.
- Registering before implementation exists.
- Using inconsistent tags.
- Treating Capabilities as executable code.

---

# 14. Reference Implementation

The Web Search Capability is the canonical reference implementation.

---

# 15. `coding.*` Namespace

The Developer Intelligence Platform registers ~20 `coding.*`
Capabilities across two Modules (`coding`, `coding_agent`) --
`coding.parse`, `.symbols`, `.search`, `.references`,
`.call_hierarchy`, `.imports`, `.dependencies`, `.rename_plan`,
`.refactor_plan`, `.patch_generate`, `.document`, `.format`, `.lint`,
`.complexity`, `.duplicates`, `.dead_code`, `.project_summary`,
`.graph_query`, `.impact_analysis` (all `category=
CapabilityCategory.TOOL`, `tags={"coding", "development"}`, see
`Tool_Guide.md` §24), plus two from the Coding Agent Module:

- `coding.execute_task` -- `category=CapabilityCategory.TOOL` (backed
  by a real `ToolDriver`, `CodingAgentToolDriver`). This is a useful,
  concrete illustration of §3's category rule: a Capability's
  category is what determines its **execution backend** in Planner
  (`TOOL` -> `ToolManager`; every other category -> `ProviderManager`),
  independent of what the Capability's own tags/name/description
  suggest about its nature -- `coding.execute_task` is an
  "orchestrator"/"agent" by *description*, but must still be `TOOL` by
  *category*, or Planner will attempt to satisfy it with a Provider
  model and raise `NoAvailableProviderModelError`.
- `coding.plan_change` -- `category=CapabilityCategory.LLM`, satisfied
  by a Provider model exactly like `chat.respond`. Never registered
  with a Tool.

Both are registered from the single `coding_agent` Module (§4's "one
Module" rule), together, in `CodingAgentModuleDriver.start()`.

---

# 16. `vision.*` Namespace

The Vision Module (`parika/modules/vision/`) registers thirty-one
`vision.*` TOOL Capabilities -- the reusable foundation for every
image-understanding, comparison, deterministic-analysis, and editing
task -- each paired with its own internal, Provider-backed
`vision.provider_*` Capability (except the six purely deterministic
editing Capabilities, which need none), following exactly the same
two-Capability-per-name shape §15 documents for `coding.execute_task`/
`coding.plan_change` and `Module_Guide.md` §18.4 documents for
`ocr.extract_text`/`ocr.provider_extract_text`.

**Original, purely Provider-backed Capabilities** (no deterministic
algorithm applies -- every call reaches a Vision model):

| TOOL Capability (`category=CapabilityCategory.TOOL`) | Provider Capability (`category=CapabilityCategory.VISION`) |
| --- | --- |
| `vision.describe_image` | `vision.provider_describe_image` |
| `vision.answer_question` | `vision.provider_answer_question` |
| `vision.detect_objects` | `vision.provider_detect_objects` |
| `vision.analyze_scene` | `vision.provider_analyze_scene` |
| `vision.analyze_ui` | `vision.provider_analyze_ui` |
| `vision.analyze_chart` | `vision.provider_analyze_chart` |
| `vision.analyze_diagram` | `vision.provider_analyze_diagram` |
| `vision.detect_logos` | `vision.provider_detect_logos` |
| `vision.reason_about_image` | `vision.provider_reason_about_image` |

`vision.detect_logos`/`vision.reason_about_image` reuse the exact same
`VisionToolDriver` the original seven use -- no classical, non-learned
algorithm in this codebase can identify *which* brand a logo belongs
to, or reason open-endedly about an image, so both take this Module's
cheapest path (one more `VisionToolSpec` entry, zero new driver code).

**Deterministic-first Capabilities** (Phase 1-4 of the Vision
extension): each *always* runs a classical, non-learned algorithm
first (perceptual hashing, variance-of-Laplacian blur, Haar-cascade
face detection, ZBar QR/barcode decoding, Otsu-threshold blob
counting, statistical anomaly scanning, ...) and only additionally
dispatches to its own `vision.provider_*` Capability when the caller
explicitly asks for a semantic narration/explanation on top of the
already-computed deterministic result, or when the task is genuinely,
unavoidably semantic (`vision.search_images`, `vision.classify_image`
with open-set labels, `vision.count_objects` for a named object type):

| TOOL Capability | Provider Capability | Deterministic algorithm |
| --- | --- | --- |
| `vision.compare_images` | `vision.provider_compare_images` | perceptual hash + pixel + histogram similarity |
| `vision.detect_differences` | `vision.provider_detect_differences` | thresholded pixel diff + connected components |
| `vision.count_objects` | `vision.provider_count_objects` | Otsu threshold + connected-component blob count |
| `vision.classify_image` | `vision.provider_classify_image` | edge density/color-cardinality heuristic |
| `vision.detect_faces` | `vision.provider_detect_faces` | Haar-cascade face detection (OpenCV) |
| `vision.detect_qr_codes` | `vision.provider_detect_qr_codes` | ZBar QR decoding (`pyzbar`) |
| `vision.detect_barcodes` | `vision.provider_detect_barcodes` | ZBar barcode decoding (`pyzbar`) |
| `vision.analyze_image_quality` | `vision.provider_analyze_image_quality` | resolution/sharpness/contrast/brightness score |
| `vision.detect_blur` | `vision.provider_detect_blur` | variance of Laplacian |
| `vision.detect_rotation` | `vision.provider_detect_rotation` | row-projection-profile orientation guess |
| `vision.detect_anomalies` | `vision.provider_detect_anomalies` | grid block z-score outlier scan |
| `vision.search_images` | `vision.provider_search_images` | none -- genuinely semantic, capped by `max_candidates` |
| `vision.find_similar_images` | `vision.provider_find_similar_images` | perceptual-hash ranking across candidates |
| `vision.find_duplicates` | `vision.provider_find_duplicates` | perceptual-hash Hamming-distance clustering |

**Deterministic-only editing Capabilities** (Phase 5): pure Pillow
transforms writing a new image file through the existing
`filesystem.write` Capability; never register a Provider Capability at
all:

`vision.crop_image`, `vision.resize_image`, `vision.rotate_image`,
`vision.flip_image`, `vision.convert_format`, `vision.compress_image`.

**Hybrid editing Capabilities**: run a deterministic pipeline by
default and only add a Provider-backed note when an `instruction` is
supplied (never to alter the deterministic pixels themselves):

| TOOL Capability | Provider Capability | Deterministic algorithm |
| --- | --- | --- |
| `vision.enhance_image` | `vision.provider_enhance_image` | auto-contrast + unsharp mask (+ optional denoise) |
| `vision.remove_background` | `vision.provider_remove_background` | classical GrabCut segmentation (OpenCV) |

Every TOOL Capability above is backed by a real `ToolDriver` (one
instance per Capability -- either the shared `VisionToolDriver` or one
of `driver_compare.py`/`driver_counting.py`/`driver_detection.py`/
`driver_quality.py`/`driver_collection.py`/`driver_editing.py`'s
dedicated classes), so -- exactly like `coding.execute_task` -- each
must be `category=CapabilityCategory.TOOL` regardless of how
"AI-driven" its description sounds. Every Provider Capability is
`category=CapabilityCategory.VISION`, satisfied by a Vision-capable
Provider model (e.g. `minicpm-v4.5`), never registered with a Tool,
and never advertised to the general chat model. All thirty-one
Capabilities (plus their 25 Provider Capabilities) are registered
from the single `vision` Module (§4's "one Module" rule), together, in
`VisionModuleDriver.start()`. See `Module_Guide.md` §18.5 for the full
orchestration detail.

Face detection, background removal, and QR/barcode decoding require
the optional `vision` dependency group (`opencv-python-headless`,
`pyzbar`) -- gracefully degrading (a clear
`VisionDependencyUnavailableError`, never a crash) when not installed,
exactly like the `ocr` extra's own precedent
(`parika/modules/vision/config.py`).

---

# 17. `ocr.*` Namespace

The OCR Module (`parika/modules/ocr/`) registers eight `ocr.*` TOOL
Capabilities, all built on top of the *same* two original Capabilities
-- `ocr.extract_text`'s Filesystem-then-Provider shape, and the
`ocr.provider_extract_text` Provider Capability itself -- rather than
one Provider Capability per Tool, since every extraction below needs
the identical `required_specializations={"ocr"}` selection criterion:

| TOOL Capability (`category=CapabilityCategory.TOOL`) | Reuses `ocr.provider_extract_text`? |
| --- | --- |
| `ocr.extract_text` | Always |
| `ocr.detect_orientation` | Never (fully deterministic) |
| `ocr.detect_quality` | Never (fully deterministic) |
| `ocr.detect_language` | Only when no `text` argument is already given |
| `ocr.extract_layout` | Only when no `text` argument is already given |
| `ocr.extract_table` | Always |
| `ocr.extract_form` | Always |

`ocr.provider_extract_text` (`category=CapabilityCategory.OCR`) remains
the single Provider Capability behind every row above that needs a
model call -- satisfied by an OCR-specialized Provider model (e.g.
`glm-ocr`), never registered with a Tool, and never advertised to the
general chat model. All eight Capabilities are registered from the
single `ocr` Module (§4's "one Module" rule), together, in
`OcrModuleDriver.start()`.

`ocr.detect_language`/`ocr.extract_layout` accept either an
already-recognized `text` argument (zero additional Capability
execution at all) or a `path` fallback, letting a caller that already
ran `ocr.extract_text` reuse its output at no further cost -- the
"Make new capabilities composable" principle applied directly to
Capability registration, not just driver code.

See `Module_Guide.md` §18.4/§18.4.1 for the full orchestration detail,
including which Capabilities are fully deterministic (never reach a
Provider at all) and the optional `ocr` dependency group they require.

---

# 18. `document.*` Namespace

The Document Module (`parika/modules/document/`) is PARIKA's single
entry point for document processing -- it registers thirty-four
`document.*` TOOL Capabilities plus one shared, internal Provider
Capability, `document.provider_analyze_content`
(`category=CapabilityCategory.LLM`), never advertised to the general
chat model:

| Group | TOOL Capabilities | Ever reaches a Provider model? |
| --- | --- | --- |
| Reading | `extract_text`, `read_pdf`, `read_docx`, `read_pptx`, `read_xlsx`, `read_markdown`, `read_html`, `read_txt`, `read_csv`, `read_json`, `read_xml` | Only `extract_text`/`read_pdf`, and only indirectly -- delegated entirely to the existing `ocr.extract_text` Capability for scanned/image-only PDFs, never a new Provider call of its own. |
| Extraction | `extract_metadata`, `extract_images`, `extract_tables`, `extract_links`, `extract_headings`, `extract_sections`, `extract_references`, `extract_attachments` | Never (fully deterministic). |
| Analysis (semantic) | `summarize`, `answer_question`, `compare_documents`, `classify`, `detect_document_type`, `extract_entities`, `extract_action_items`, `extract_timeline`, `translate` | Always (`document.provider_analyze_content`). |
| Analysis (deterministic) | `search`, `detect_language`, `extract_keywords`, `extract_dates`, `extract_contacts`, `detect_duplicates` | Never. |

`document.extract_text` (formerly a temporary implementation detail of
the OCR Module) is the universal, auto-detecting entry point; the ten
`document.read_*` Capabilities are its format-fixed counterparts. Every
Reading/Extraction Capability maps its format into one
provider-independent `UnifiedDocument` (`document_model.py`); every
semantic Analysis Capability shares the *same* Provider Capability,
differing only in its instruction and input arguments -- mirroring
§16/§17's own single-shared-Provider-Capability precedent exactly.

See `Module_Guide.md` §18.6 for the full orchestration detail,
including the native-parser-first/OCR-fallback Document Pipeline and
the optional `document` dependency group (`python-docx`,
`python-pptx`, `openpyxl`, `beautifulsoup4`).

---

# 19. `video.*` Namespace

The Video Module (`parika/modules/video/`) registers thirty `video.*`
TOOL Capabilities plus six internal Provider Capabilities of its own
(`category=CapabilityCategory.VISION` -- see `Module_Guide.md` §18.7
for why this Module reuses `VISION` rather than a new category),
never advertised to the general chat model. Every other Provider-
backed row below reuses a *sibling* Module's own Provider Capability
directly instead of registering a new one:

| Group | TOOL Capabilities | Ever reaches a Provider model? |
| --- | --- | --- |
| I/O | `read_video`, `extract_metadata`, `extract_frames`, `extract_keyframes`, `extract_thumbnails` | Never (fully deterministic). |
| Video understanding | `describe_video`, `summarize_video`, `answer_question`, `classify_video` | Always for `describe_video`/`summarize_video`/`answer_question` (this Module's own `video.provider_*`); `classify_video` only when `candidate_labels` are supplied. |
| Timeline | `generate_timeline`, `detect_scene_changes`, `detect_shots`, `segment_video`, `detect_key_moments` | `generate_timeline` optionally (per-keyframe narration via `vision.provider_describe_image`); `detect_key_moments` optionally (`video.provider_detect_key_moments`); the rest never. |
| Objects and motion | `detect_objects`, `count_objects`, `track_objects`, `detect_motion`, `compare_frames` | `detect_objects`/`track_objects` always (`vision.provider_detect_objects`); `count_objects` only for a named `candidate_object`; `detect_motion`/`compare_frames` never. |
| Events, text, documents | `detect_events`, `detect_actions`, `extract_text`, `detect_documents`, `detect_slides`, `extract_tables` | `detect_actions` always (`video.provider_detect_actions`); `extract_text`/`detect_documents`/`extract_tables` always (`ocr.provider_extract_text`); `detect_events`/`detect_slides` never. |
| Comparison and quality | `compare_videos`, `detect_blur`, `detect_black_frames`, `detect_rotation`, `detect_corruption` | `compare_videos` only when `include_semantic_diff` is set (`vision.provider_compare_images`); the rest never. |

`video.detect_objects`/`video.extract_text` are this Module's
`document.extract_text`-equivalent universal reuse points: rather than
a Tool-level nested `Goal` (which would require writing every sampled
in-memory frame back out to a file merely to satisfy Vision's/OCR's
own `path` argument), they target the sibling Module's *Provider*
Capability directly with the frame's already-in-memory base64 bytes
(`engine.analyze_frames_with_provider()`) -- the same dynamic,
Goal-based resolution every other cross-Module reuse in this Guide
uses, just one level lower in the Tool/Provider pair.

See `Module_Guide.md` §18.7 for the full orchestration detail,
including the deterministic frame-sampling/scene-detection algorithms
and the optional `video` dependency group (`opencv-python-headless`,
shared with the `vision` extra).

---

# 20. `media.*` Namespace

The Media Module (`parika/modules/media/`) registers thirteen
`media.*` TOOL Capabilities and no internal Provider Capability at
all -- unlike every namespace above, nothing here ever reaches a
Provider model. See ADR 0004
(`docs/architecture/adr/0004-media-capability.md`) for the full
architectural decision.

| Group | TOOL Capabilities | Ever reaches a Provider model? |
| --- | --- | --- |
| Playback commands | `play`, `pause`, `resume`, `stop`, `skip`, `previous`, `seek`, `set_volume`, `mute`, `unmute`, `show`, `hide` | Never. Each dispatches a command over `WS /api/v1/ws/media/{client_id}` to a separate, connected Web Client, which performs actual playback -- PARIKA server never decodes/streams/plays audio or video itself. |
| State | `get_state` | Never. A pure read of PARIKA's last known `MediaState`; never dispatches anything. |

`media.play`'s free-text resolution (e.g. "Imagine Dragons Believer")
reuses the existing `web.search` Capability through the same nested-
`Goal`-via-`Brain.handle()` pattern every cross-Capability reuse in
this Guide uses -- never a hardcoded YouTube API client. Local-file
resolution is confined to an explicit, empty-by-default
`[media].allowed_local_roots` allowlist (see
`parika/tools/media/security.py`), deliberately narrower than the
Filesystem Tool's own default-open reads, since a resolved source's
raw path is returned to the caller.

See `docs/guides/Running.md`'s Media API section for the full
bidirectional Server-to-Web-Client/Web-Client-to-Server command/event
contract this namespace implements, including the "Web Client Media
Integration Contract" the future, separate Web Client is built
against.

---

# Related Documentation

- architecture/PARIKA_Architecture_Specification_v1.0.md
- architecture/Core_Component_Responsibilities.md
- architecture/PARIKA_Decision_Flow.md
- development/Module_Guide.md
- development/Tool_Guide.md
- development/Integration_Checklist.md
- guides/Running.md
- guides/Testing.md
