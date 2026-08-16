"""
PARIKA Utilities - Progress Reporting

Provides a small, generic, ecosystem-wide progress-reporting mechanism
reused by every present and future Tool and Module (Filesystem Tool,
Shell Tool, Coding Tool, Web Search Tool, Repository Intelligence, the
Coding Agent, ...).

This module activates the `Utilities` Core component
(`docs/architecture/Core_Component_Responsibilities.md` section 5),
which has been reserved, empty, since v1.0 for exactly this class of
low-level, cross-cutting helper functionality. It introduces no new
Core component: `ProgressReporter` has no lifecycle, no registry, and
no business logic beyond formatting an immutable event and delegating
to the existing, unmodified `EventBus`.

See docs/architecture/Core_Component_Responsibilities.md
Addendum A and Addendum B for the full design rationale.

Design summary
---------------
- Every progress-reporting call publishes one immutable `ProgressEvent`
  to two `EventBus` channels: a specific channel named
  ``f"{source_id}.{stage}"`` (e.g. ``"filesystem.search.started"``) and
  a fixed, generic channel named ``f"progress.{stage}"`` (e.g.
  ``"progress.started"``). `EventBus.subscribe()` matches by exact
  string name with no wildcard support, so the generic channel is what
  lets any Interface subscribe once, for the process's lifetime, and
  receive progress for every present and future Tool/Module with zero
  code change -- never by hardcoding every capability id in advance.
- Hierarchy (nested progress) is expressed by building a tree of
  `ProgressReporter` instances via `ProgressReporter.child()`. Every
  node's identity (`progress_id`, `parent_progress_id`, `task_id`,
  `progress_path`) is set once at construction and never changes for
  that node's lifetime.
- `task_id` (correlating to `TaskManager.Task.id`, when known) and
  `progress_id` (identifying one node in the reporting tree) are
  deliberately distinct identifiers: a single Task's execution may
  contain an entire tree of progress nodes that are never themselves
  separate Tasks.
- This module implements no cancellation and no background scheduling.
  `cancellable`/`task_id` are carried purely so that a future increment
  (not part of this phase) can build on them without any redesign of
  this payload.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from parika.core.event_bus.event_bus import EventBus

GENERIC_PROGRESS_CHANNEL_PREFIX = "progress"
"""Fixed prefix for the generic, ecosystem-wide progress channel names
(``progress.started``, ``progress.progress``, ``progress.completed``,
``progress.failed``)."""


class ProgressStage(StrEnum):
    """
    The closed, fixed set of stages every progress-reporting node may
    be in.

    Kept deliberately small so that any subscriber only ever needs to
    handle four stage kinds, never an open-ended set of stage names per
    Tool. A more specific human-readable label (e.g. "Reading search
    results...") belongs in `ProgressEvent.message`, not in a new
    stage name.
    """

    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgressEvent:
    """
    Immutable payload published for every progress-reporting stage
    transition.

    `source_id` is a stable, generic, dotted identifier describing what
    *kind* of step is reporting (a Capability id such as
    ``"filesystem.search"``/``"coding.index"`` when the reporter
    belongs to a registered Tool operation, or a
    ``"<module_id>.<internal_step>"`` identifier such as
    ``"repository_intelligence.discover_workspace"`` for an internal
    engine/analyzer step with no Capability of its own). Instance-
    specific identity (which repository, which file) belongs in
    `metadata`, never appended into `source_id` itself.
    """

    source_id: str
    stage: ProgressStage

    progress_id: str
    """Unique, stable identifier of this reporting node. Generated once
    when its `ProgressReporter` is constructed; identical across that
    node's started/progress/completed/failed events."""

    parent_progress_id: str | None = None
    """The immediate parent node's `progress_id`. `None` for a root
    node."""

    progress_path: tuple[str, ...] = ()
    """Every ancestor's `progress_id`, root-first, ending with this
    node's own `progress_id`. Lets a subscriber reconstruct a node's
    full ancestry even if it never observed that node's ancestors' own
    `started` events -- necessary because `EventBus` never persists
    events or maintains event history."""

    task_id: str | None = None
    """Correlates to `TaskManager`'s `Task.id`, when known. Distinct
    from `progress_id` -- see this module's docstring."""

    message: str | None = None
    """Human-readable status text, always supplied by the component
    that is itself doing the work -- never fabricated by a caller/
    orchestrator narrating another component's internal work."""

    current: int | None = None
    total: int | None = None
    percent: float | None = None
    """Auto-derived from `current`/`total` when both are given; `None`
    when the operation is not determinate."""

    warnings: tuple[str, ...] = ()
    cancellable: bool = False
    """Informational only in this phase -- no cancellation is
    implemented or enforced by this module."""

    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    emitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """
        Guarantee immutability of mutable-looking fields.
        """

        object.__setattr__(self, "progress_path", tuple(self.progress_path))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


class ProgressReporter:
    """
    Small, stateless-except-for-identity helper that publishes
    `ProgressEvent`s through the existing `EventBus`.

    Not a Core component in its own right: no lifecycle, no registry,
    no business logic beyond formatting and delegating to `EventBus`.
    Every present and future Tool/Module operation that wants to
    report its own progress constructs (or receives, by dependency
    injection) one `ProgressReporter` bound to its own `source_id`, and
    calls `started()`/`progress()`/`completed()`/`failed()` at the
    points in its own control flow where those transitions genuinely
    happen. A nested step is reported by calling `child()` to obtain a
    new reporter one level beneath the current one; nesting is
    expressed entirely by the resulting `progress_id`/
    `parent_progress_id`/`progress_path` values, never by a new event
    name.
    """

    __slots__ = (
        "_event_bus",
        "_source_id",
        "_task_id",
        "_progress_id",
        "_parent_progress_id",
        "_progress_path",
    )

    def __init__(
        self,
        event_bus: EventBus,
        source_id: str,
        *,
        task_id: str | None = None,
        progress_id: str | None = None,
        parent_progress_id: str | None = None,
        progress_path: tuple[str, ...] = (),
    ) -> None:
        """
        Initialize a `ProgressReporter`.

        Args:
            event_bus:
                The existing, unmodified Core `EventBus` every event is
                published through.

            source_id:
                Stable, generic, dotted identifier for this node's
                kind of step (see `ProgressEvent.source_id`).

            task_id:
                Optional identifier correlating to a `TaskManager`
                `Task.id`. Inherited by `child()` unless overridden.

            progress_id:
                Optional explicit identifier for this node. Generated
                (`uuid4().hex`) when omitted -- the normal case for a
                root reporter.

            parent_progress_id:
                Optional immediate parent node's `progress_id`. `None`
                for a root reporter.

            progress_path:
                Optional explicit ancestor path (root-first, excluding
                this node). When omitted, this reporter is treated as
                its own root for path purposes.
        """

        self._event_bus = event_bus
        self._source_id = source_id
        self._task_id = task_id
        self._progress_id = (
            progress_id if progress_id is not None else uuid4().hex
        )
        self._parent_progress_id = parent_progress_id
        self._progress_path = (*progress_path, self._progress_id)

    @property
    def progress_id(self) -> str:
        """
        The stable identifier of this reporting node.
        """

        return self._progress_id

    @property
    def source_id(self) -> str:
        """
        The stable, generic identifier this reporter publishes under.
        """

        return self._source_id

    def child(
        self,
        source_id: str,
        *,
        task_id: str | None = None,
    ) -> "ProgressReporter":
        """
        Return a new `ProgressReporter` one level beneath this one.

        Does not itself publish anything -- the caller still
        explicitly calls `started()`/`progress()`/`completed()`/
        `failed()` on the returned child, exactly like any root
        `ProgressReporter`.

        Args:
            source_id:
                Stable, generic identifier for the child node's kind
                of step.

            task_id:
                Optional explicit `Task.id` override for the child.
                Defaults to this reporter's own `task_id` when
                omitted, since a nested step is normally still part of
                the same outer unit of work.
        """

        return ProgressReporter(
            self._event_bus,
            source_id,
            task_id=task_id if task_id is not None else self._task_id,
            parent_progress_id=self._progress_id,
            progress_path=self._progress_path,
        )

    def started(self, message: str | None = None, **metadata: Any) -> None:
        """
        Report that this node's work has begun.
        """

        self._publish(ProgressStage.STARTED, message=message, metadata=metadata)

    def progress(
        self,
        *,
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
        warnings: tuple[str, ...] = (),
        **metadata: Any,
    ) -> None:
        """
        Report an intermediate progress update for this node.

        `percent` is derived automatically from `current`/`total` when
        both are supplied.
        """

        percent = (
            (current / total) * 100.0
            if current is not None and total is not None and total > 0
            else None
        )

        self._publish(
            ProgressStage.PROGRESS,
            message=message,
            current=current,
            total=total,
            percent=percent,
            warnings=warnings,
            metadata=metadata,
        )

    def completed(self, message: str | None = None, **metadata: Any) -> None:
        """
        Report that this node's work finished successfully.
        """

        self._publish(ProgressStage.COMPLETED, message=message, metadata=metadata)

    def failed(self, message: str | None = None, **metadata: Any) -> None:
        """
        Report that this node's work terminated with an error.
        """

        self._publish(ProgressStage.FAILED, message=message, metadata=metadata)

    def _publish(
        self,
        stage: ProgressStage,
        *,
        message: str | None,
        current: int | None = None,
        total: int | None = None,
        percent: float | None = None,
        warnings: tuple[str, ...] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        event = ProgressEvent(
            source_id=self._source_id,
            stage=stage,
            progress_id=self._progress_id,
            parent_progress_id=self._parent_progress_id,
            progress_path=self._progress_path,
            task_id=self._task_id,
            message=message,
            current=current,
            total=total,
            percent=percent,
            warnings=warnings,
            metadata=metadata or {},
        )

        self._event_bus.publish(f"{self._source_id}.{stage.value}", event)
        self._event_bus.publish(
            f"{GENERIC_PROGRESS_CHANNEL_PREFIX}.{stage.value}", event
        )


class NullProgressReporter(ProgressReporter):
    """
    A `ProgressReporter` that never publishes anything.

    Used as a safe, no-op default for callers that construct a
    component without an `EventBus` available (e.g. isolated unit
    tests), so those components never need `None`-checks scattered
    through their own control flow.
    """

    def __init__(self, source_id: str = "null") -> None:
        super().__init__(_NullEventBus(), source_id)


class _NullEventBus:
    """
    Minimal stand-in exposing only the `publish()` method
    `ProgressReporter` calls, used exclusively by
    `NullProgressReporter`.
    """

    def publish(self, event_name: str, payload: Any = None) -> None:
        return None
