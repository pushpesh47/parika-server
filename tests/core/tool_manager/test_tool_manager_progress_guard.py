"""
Regression tests for ToolManager's shared ProgressReporter lifecycle
guard (`ToolManager._execute_driver_with_progress_guard()`).

Context (see the audit report this fix implements): individual
ToolDrivers commonly own their own `ProgressReporter` and call
`self._progress.started()`/`.completed()`/`.failed()` around their own
work. If a driver's `execute()` raises after `started()` but before
its own `.completed()`/`.failed()`, that progress node is left open
forever -- the CLI spinner (`parika/console/spinner_view.py`) never
returns to idle. This was found, and independently fixed one driver at
a time, in OCR/Document and Vision's detection drivers, then
reproduced again in the new Image/Video generation drivers.

These tests exercise the fix at the one shared boundary every
ToolDriver -- current and future -- already passes through
(`ToolManager.execute()`), using synthetic drivers for capability ids
that do not exist anywhere else in the codebase, so the guarantee is
proven to be capability-id-agnostic rather than specific to today's
Image/Video drivers.

A follow-up correctness audit found a concurrency defect in the guard
described above: it correlated `progress.*` events using only
bookkeeping that implicitly assumed "every event observed while I am
subscribed belongs to me", which is only true under sequential/nested
execution and is false once two `ToolManager.execute()` calls
genuinely overlap on a shared `EventBus` -- one execution's guard could
synthesize a spurious `failed()` for a *different*, concurrently
running execution's still-active progress node. The
`TestConcurrentExecution` classes below reproduce that exact defect
deterministically (via `threading.Barrier`-gated drivers, not timing
luck) and prove the fix (execution-ownership correlation via a
`contextvars.ContextVar`, see
`ToolManager._execute_driver_with_progress_guard()`) closes it, while
`TestNestedExecution` proves the same fix does not regress the
already-verified nested/sequential lifecycle, and
`TestOriginalExceptionPreservation` proves a failure in the cleanup
mechanism itself can never mask the original driver exception.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.tool_manager.exceptions import ToolExecutionError
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressReporter, ProgressStage


class ProgressLifecycleRecorder:
    """
    Subscribes to the generic `progress.*` channels and records every
    `progress.started` event alongside every matching
    `progress.completed`/`progress.failed` event, keyed by
    `ProgressEvent.progress_id`.

    Mirrors `tests/conftest.py`'s helper of the same name (duplicated
    locally, matching this test module's existing convention of
    keeping small test doubles self-contained -- see
    `RecordingSubscriber` in `test_tool_manager.py`).
    """

    def __init__(self, event_bus: EventBus) -> None:
        self.started_events: dict[str, list[Any]] = {}
        self.terminal_events: dict[str, list[Any]] = {}

        event_bus.subscribe("progress.started", self._on_started)
        event_bus.subscribe("progress.completed", self._on_terminal)
        event_bus.subscribe("progress.failed", self._on_terminal)

    def _on_started(self, event: Any) -> None:
        self.started_events.setdefault(event.progress_id, []).append(event)

    def _on_terminal(self, event: Any) -> None:
        self.terminal_events.setdefault(event.progress_id, []).append(event)

    def assert_every_started_has_exactly_one_terminal(self) -> None:
        for progress_id, starts in self.started_events.items():
            terminals = self.terminal_events.get(progress_id, [])
            assert len(terminals) == 1, (
                f"progress_id {progress_id!r} (source_id "
                f"{starts[0].source_id!r}) started {len(starts)} "
                f"time(s) but received {len(terminals)} terminal "
                f"event(s); expected exactly 1."
            )

        for progress_id in self.terminal_events:
            assert progress_id in self.started_events, (
                f"progress_id {progress_id!r} received a terminal "
                "event without ever starting."
            )


class _FutureNaiveDriver:
    """
    A ToolDriver for a brand-new capability that reports its own
    progress using the exact unsafe shape the audit report calls out
    (`started()` ... `completed()`, no enclosing try/except, no
    `failed()` on any path) -- i.e. a driver author who implemented
    nothing beyond the normal ToolDriver contract and never learned
    about, or remembered, any special lifecycle trick.
    """

    def __init__(
        self,
        *,
        progress_reporter: ProgressReporter,
        should_fail: bool,
    ) -> None:
        self._progress = progress_reporter
        self._should_fail = should_fail

    def execute(self, request: ToolRequest) -> ToolResponse:
        self._progress.started(message="Doing work...")

        if self._should_fail:
            raise RuntimeError("perform_operation() failed.")

        self._progress.completed(message="Completed.")

        return ToolResponse(result="ok")


class _AlreadyFixedDriver:
    """
    The reference-safe shape already used by OCR/Document/Vision's
    detection drivers: `started()` -> `try:` -> `completed()` on
    success, or `except Exception: failed(); raise` on failure. Used
    to prove the shared guard never fires a second, duplicate
    terminal event for a driver that already terminates its own
    progress node.
    """

    def __init__(
        self,
        *,
        progress_reporter: ProgressReporter,
        should_fail: bool,
    ) -> None:
        self._progress = progress_reporter
        self._should_fail = should_fail

    def execute(self, request: ToolRequest) -> ToolResponse:
        self._progress.started(message="Doing work...")

        try:
            if self._should_fail:
                raise RuntimeError("perform_operation() failed.")

            self._progress.completed(message="Completed.")

            return ToolResponse(result="ok")

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise


class _NestedInnerDriver:
    """
    A naive future-style driver (see `_FutureNaiveDriver`) registered
    as the *inner* Tool in nested-execution tests, so the nested,
    reentrant `ToolManager.execute()` call itself goes through
    `_execute_driver_with_progress_guard()` a second time -- exactly
    the shape a Coding Agent Tool driver's own nested tool call
    produces (see `parika/modules/coding_agent/`), not merely a
    driver that reports a nested progress node without a second
    `ToolManager.execute()` call.
    """

    def __init__(
        self,
        *,
        progress_reporter: ProgressReporter,
        should_fail: bool,
    ) -> None:
        self._progress = progress_reporter
        self._should_fail = should_fail

    def execute(self, request: ToolRequest) -> ToolResponse:
        self._progress.started(message="inner started")

        if self._should_fail:
            raise RuntimeError("inner tool failed")

        self._progress.completed(message="inner completed")

        return ToolResponse(result="inner-ok")


class _NestedOuterDriver:
    """
    A naive future-style outer driver whose own `execute()` reenters
    `ToolManager.execute()` for a nested inner Tool, then always fails
    on its own afterward -- regardless of whether the nested call
    itself succeeded or failed -- to exercise both of the audit
    report's required nested scenarios ("inner completed, outer
    failed" and "inner failed, outer failed") with one driver.
    """

    def __init__(
        self,
        *,
        tool_manager: ToolManager,
        inner_tool_id: str,
        progress_reporter: ProgressReporter,
    ) -> None:
        self._tool_manager = tool_manager
        self._inner_tool_id = inner_tool_id
        self._progress = progress_reporter

    def execute(self, request: ToolRequest) -> ToolResponse:
        self._progress.started(message="outer started")

        try:
            self._tool_manager.execute(self._inner_tool_id, ToolRequest())

        except ToolExecutionError:
            # The nested call's own guard/exception-wrapping already
            # ran; the outer driver still fails on its own below
            # either way, mirroring a Coding Agent step that reports
            # its own overall failure after a nested tool call fails.
            pass

        raise RuntimeError("outer tool failed after nested call")


class _BarrierGatedDriver:
    """
    A naive future-style driver used only by the concurrency tests
    below. Reports `started()`, then blocks on a shared
    `threading.Barrier` so two concurrently executed drivers are
    *guaranteed* to both have reported `started()` before either is
    allowed to proceed, then sleeps for its own configured duration
    before finishing -- making the historically observed race ("A
    fails while B is still executing, and A's guard spuriously fires
    B's `failed()`") deterministic and reliably reproducible rather
    than dependent on incidental thread-scheduling timing.
    """

    def __init__(
        self,
        *,
        progress_reporter: ProgressReporter,
        barrier: threading.Barrier,
        delay_seconds: float,
        should_fail: bool,
        tag: str,
        log: list[str],
        log_lock: threading.Lock,
    ) -> None:
        self._progress = progress_reporter
        self._barrier = barrier
        self._delay_seconds = delay_seconds
        self._should_fail = should_fail
        self._tag = tag
        self._log = log
        self._log_lock = log_lock

    def _record(self, event: str) -> None:
        with self._log_lock:
            self._log.append(f"{self._tag} {event}")

    def execute(self, request: ToolRequest) -> ToolResponse:
        self._progress.started(message=f"{self._tag} started")
        self._record("started")

        # Block until both concurrent drivers have reported started(),
        # then race their own independent, deliberately different
        # delays -- never each other's subscribe/unsubscribe timing.
        self._barrier.wait(timeout=5.0)
        time.sleep(self._delay_seconds)

        if self._should_fail:
            self._record("failed")
            raise RuntimeError(f"{self._tag} tool failed")

        self._progress.completed(message=f"{self._tag} completed")
        self._record("completed")

        return ToolResponse(result=f"{self._tag}-ok")


def _make_tool(**overrides: Any) -> Tool:
    fields: dict[str, Any] = {
        "id": "example.generate",
        "name": "Example Tool",
        "version": "1.0.0",
        "description": "A synthetic future tool used in tests.",
    }
    fields.update(overrides)
    return Tool(**fields)


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


class TestFutureStyleDriver:
    """
    Scenarios 1-3, 6, 7, 9 from the fix's acceptance criteria: a
    completely new, naive ToolDriver is protected without any
    special-casing of its capability id.
    """

    def test_success_reports_started_then_completed(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        recorder = ProgressLifecycleRecorder(event_bus)
        progress = ProgressReporter(event_bus, "example.generate")
        driver = _FutureNaiveDriver(progress_reporter=progress, should_fail=False)
        tool = _make_tool()
        tool_manager.register(tool, driver)

        response = tool_manager.execute(tool.id, ToolRequest())

        assert response.result == "ok"

        recorder.assert_every_started_has_exactly_one_terminal()
        terminal = recorder.terminal_events[progress.progress_id]
        assert terminal[0].stage is ProgressStage.COMPLETED

    def test_exception_reports_started_then_failed(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        recorder = ProgressLifecycleRecorder(event_bus)
        progress = ProgressReporter(event_bus, "example.generate")
        driver = _FutureNaiveDriver(progress_reporter=progress, should_fail=True)
        tool = _make_tool()
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(tool.id, ToolRequest())

        recorder.assert_every_started_has_exactly_one_terminal()
        terminal = recorder.terminal_events[progress.progress_id]
        assert terminal[0].stage is ProgressStage.FAILED

    def test_exception_still_propagates_through_the_normal_failure_chain(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        progress = ProgressReporter(event_bus, "example.generate")
        original_error = RuntimeError("perform_operation() failed.")
        driver = _FutureNaiveDriver(progress_reporter=progress, should_fail=True)
        tool = _make_tool()
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError) as excinfo:
            tool_manager.execute(tool.id, ToolRequest())

        # The guard never swallows or replaces the original exception
        # -- ToolManager's existing exception semantics (wrapping in
        # ToolExecutionError with `__cause__` set) are unchanged.
        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert str(excinfo.value.__cause__) == str(original_error)

    def test_arbitrary_never_before_seen_capability_id_is_protected(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        # The guard must not depend on any hardcoded capability/tool
        # id -- this id matches none of spinner_view.py's known
        # keywords and does not exist anywhere else in the codebase.
        recorder = ProgressLifecycleRecorder(event_bus)
        progress = ProgressReporter(
            event_bus, "zzz_totally_unknown_future_capability"
        )
        driver = _FutureNaiveDriver(progress_reporter=progress, should_fail=True)
        tool = _make_tool(id="zzz_totally_unknown_future_capability")
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(tool.id, ToolRequest())

        recorder.assert_every_started_has_exactly_one_terminal()

    def test_synthetic_terminal_event_reuses_the_started_progress_id(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        progress = ProgressReporter(event_bus, "example.generate")
        driver = _FutureNaiveDriver(progress_reporter=progress, should_fail=True)
        tool = _make_tool()
        tool_manager.register(tool, driver)

        captured: list[Any] = []
        event_bus.subscribe("progress.failed", captured.append)

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(tool.id, ToolRequest())

        assert len(captured) == 1
        assert captured[0].progress_id == progress.progress_id
        assert captured[0].source_id == "example.generate"

    def test_no_progress_node_remains_active_after_failed_execution(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        # Mirrors `SpinnerProgressRenderer._active` (spinner_view.py):
        # incremented on every `progress.started`, decremented on
        # every `progress.completed`/`progress.failed`. This is the
        # actual CLI-visible invariant the fix restores.
        active = 0

        def _on_started(event: Any) -> None:
            nonlocal active
            active += 1

        def _on_terminal(event: Any) -> None:
            nonlocal active
            active -= 1

        event_bus.subscribe("progress.started", _on_started)
        event_bus.subscribe("progress.completed", _on_terminal)
        event_bus.subscribe("progress.failed", _on_terminal)

        progress = ProgressReporter(event_bus, "video.generate")
        driver = _FutureNaiveDriver(progress_reporter=progress, should_fail=True)
        tool = _make_tool(id="video.generate")
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(tool.id, ToolRequest())

        assert active == 0


class TestAlreadyFixedDriverCompatibility:
    """
    Scenarios 4-5: drivers that already implement the reference-safe
    pattern (OCR/Document/Vision-detection style) must not receive a
    second, duplicate terminal event when executed through the new
    shared guard.
    """

    def test_existing_failed_call_is_not_duplicated(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        recorder = ProgressLifecycleRecorder(event_bus)
        progress = ProgressReporter(event_bus, "ocr.extract_text")
        driver = _AlreadyFixedDriver(progress_reporter=progress, should_fail=True)
        tool = _make_tool(id="ocr.extract_text")
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(tool.id, ToolRequest())

        recorder.assert_every_started_has_exactly_one_terminal()
        terminal = recorder.terminal_events[progress.progress_id]
        assert len(terminal) == 1
        assert terminal[0].stage is ProgressStage.FAILED

    def test_existing_successful_driver_still_reports_exactly_one_completed(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        recorder = ProgressLifecycleRecorder(event_bus)
        progress = ProgressReporter(event_bus, "ocr.extract_text")
        driver = _AlreadyFixedDriver(progress_reporter=progress, should_fail=False)
        tool = _make_tool(id="ocr.extract_text")
        tool_manager.register(tool, driver)

        tool_manager.execute(tool.id, ToolRequest())

        recorder.assert_every_started_has_exactly_one_terminal()
        terminal = recorder.terminal_events[progress.progress_id]
        assert len(terminal) == 1
        assert terminal[0].stage is ProgressStage.COMPLETED


def _progress_subscription_count(event_bus: EventBus) -> int:
    """
    Total number of subscribers currently registered across the three
    generic `progress.*` channels, used to prove the guard leaves no
    `EventBus` subscription behind once a guarded call (successful,
    nested, or concurrent) has fully unwound.
    """

    return sum(
        len(subscribers)
        for name, subscribers in event_bus._subscriptions.items()  # noqa: SLF001
        if name.startswith("progress.")
    )


def _unsubscribe_recorder(
    event_bus: EventBus,
    recorder: ProgressLifecycleRecorder,
) -> None:
    """
    Remove a `ProgressLifecycleRecorder`'s own three subscriptions, so
    a test can assert `_progress_subscription_count()` returns exactly
    `0` afterward -- i.e. that nothing *other than the recorder itself*
    (in particular, no guard) leaked a subscription.
    """

    event_bus.unsubscribe("progress.started", recorder._on_started)
    event_bus.unsubscribe("progress.completed", recorder._on_terminal)
    event_bus.unsubscribe("progress.failed", recorder._on_terminal)


class TestNestedExecution:
    """
    Nested execution: a driver's own `execute()` reenters
    `ToolManager.execute()` for a second, inner Tool -- e.g. a Coding
    Agent Tool driver submitting a nested tool call -- so the shared
    guard is installed twice, on the same thread, one inside the
    other. The fix's execution-ownership `ContextVar` must not change
    this already-verified lifecycle: the outer guard must still
    synthesize exactly one terminal event for the *outer* node once
    the outer driver itself fails, and must never touch the *inner*
    node (whose own, nested guard invocation is solely responsible for
    it), in either order of inner success/failure.
    """

    def test_inner_completes_then_outer_fails(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        recorder = ProgressLifecycleRecorder(event_bus)

        inner_progress = ProgressReporter(event_bus, "nested.inner")
        inner_driver = _NestedInnerDriver(
            progress_reporter=inner_progress, should_fail=False
        )
        tool_manager.register(_make_tool(id="nested.inner"), inner_driver)

        outer_progress = ProgressReporter(event_bus, "nested.outer")
        outer_driver = _NestedOuterDriver(
            tool_manager=tool_manager,
            inner_tool_id="nested.inner",
            progress_reporter=outer_progress,
        )
        tool_manager.register(_make_tool(id="nested.outer"), outer_driver)

        with pytest.raises(ToolExecutionError):
            tool_manager.execute("nested.outer", ToolRequest())

        recorder.assert_every_started_has_exactly_one_terminal()

        inner_terminal = recorder.terminal_events[inner_progress.progress_id]
        assert len(inner_terminal) == 1
        assert inner_terminal[0].stage is ProgressStage.COMPLETED

        outer_terminal = recorder.terminal_events[outer_progress.progress_id]
        assert len(outer_terminal) == 1
        assert outer_terminal[0].stage is ProgressStage.FAILED

        _unsubscribe_recorder(event_bus, recorder)
        assert _progress_subscription_count(event_bus) == 0

    def test_inner_fails_then_outer_fails(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        recorder = ProgressLifecycleRecorder(event_bus)

        inner_progress = ProgressReporter(event_bus, "nested.inner")
        inner_driver = _NestedInnerDriver(
            progress_reporter=inner_progress, should_fail=True
        )
        tool_manager.register(_make_tool(id="nested.inner"), inner_driver)

        outer_progress = ProgressReporter(event_bus, "nested.outer")
        outer_driver = _NestedOuterDriver(
            tool_manager=tool_manager,
            inner_tool_id="nested.inner",
            progress_reporter=outer_progress,
        )
        tool_manager.register(_make_tool(id="nested.outer"), outer_driver)

        with pytest.raises(ToolExecutionError):
            tool_manager.execute("nested.outer", ToolRequest())

        # Neither node may receive a duplicate terminal event: exactly
        # one `started` and exactly one terminal event each, and the
        # inner node's terminal event must be the *inner* guard's own
        # synthetic `failed()`, never re-fired by the outer guard.
        recorder.assert_every_started_has_exactly_one_terminal()

        inner_terminal = recorder.terminal_events[inner_progress.progress_id]
        assert len(inner_terminal) == 1
        assert inner_terminal[0].stage is ProgressStage.FAILED

        outer_terminal = recorder.terminal_events[outer_progress.progress_id]
        assert len(outer_terminal) == 1
        assert outer_terminal[0].stage is ProgressStage.FAILED

        _unsubscribe_recorder(event_bus, recorder)
        assert _progress_subscription_count(event_bus) == 0


class TestConcurrentExecution:
    """
    Genuine concurrency: two `ToolManager.execute()` calls, on two real
    OS threads, sharing one `EventBus`, deliberately overlapping in
    time (via `threading.Barrier`, not incidental timing). This is the
    exact defect the correctness audit confirmed 5/5 times: the old
    guard correlated `progress.*` events using only bookkeeping that
    assumed "every event observed while I am subscribed belongs to
    me", so tool A's guard could see tool B's still-active `started`
    event and, on A's own failure, spuriously synthesize a `failed()`
    for B's progress node while B was still legitimately running.
    """

    def test_a_fails_quickly_while_b_is_still_executing(
        self,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        # A fails almost immediately after the shared barrier releases;
        # B keeps running for much longer, so if A's guard were still
        # (incorrectly) tracking B's progress node, A's failure-cleanup
        # would fire *before* B has any chance to complete on its own
        # -- reproducing "A failed" then spurious "B failed" then only
        # later "B completed" from the audit report.
        for _ in range(20):
            recorder = ProgressLifecycleRecorder(event_bus)
            log: list[str] = []
            log_lock = threading.Lock()
            barrier = threading.Barrier(2)

            tool_manager_a = ToolManager(event_bus=event_bus, logger=logger)
            tool_manager_b = ToolManager(event_bus=event_bus, logger=logger)

            progress_a = ProgressReporter(event_bus, "concurrent.a")
            driver_a = _BarrierGatedDriver(
                progress_reporter=progress_a,
                barrier=barrier,
                delay_seconds=0.0,
                should_fail=True,
                tag="a",
                log=log,
                log_lock=log_lock,
            )
            tool_manager_a.register(_make_tool(id="concurrent.a"), driver_a)

            progress_b = ProgressReporter(event_bus, "concurrent.b")
            driver_b = _BarrierGatedDriver(
                progress_reporter=progress_b,
                barrier=barrier,
                delay_seconds=0.1,
                should_fail=False,
                tag="b",
                log=log,
                log_lock=log_lock,
            )
            tool_manager_b.register(_make_tool(id="concurrent.b"), driver_b)

            results: dict[str, Any] = {}

            def _run_a() -> None:
                try:
                    tool_manager_a.execute("concurrent.a", ToolRequest())

                except Exception as ex:
                    results["a"] = ex

            def _run_b() -> None:
                try:
                    results["b"] = tool_manager_b.execute(
                        "concurrent.b", ToolRequest()
                    )

                except Exception as ex:
                    results["b"] = ex

            thread_a = threading.Thread(target=_run_a)
            thread_b = threading.Thread(target=_run_b)
            thread_a.start()
            thread_b.start()
            thread_a.join(timeout=5.0)
            thread_b.join(timeout=5.0)

            assert isinstance(results["a"], ToolExecutionError)
            assert isinstance(results["b"], ToolResponse)

            # The core assertion: B's own progress node must have
            # received exactly one terminal event, and it must be
            # `completed`, never `failed` -- A's guard must never have
            # touched it.
            recorder.assert_every_started_has_exactly_one_terminal()

            a_terminal = recorder.terminal_events[progress_a.progress_id]
            assert len(a_terminal) == 1
            assert a_terminal[0].stage is ProgressStage.FAILED

            b_terminal = recorder.terminal_events[progress_b.progress_id]
            assert len(b_terminal) == 1
            assert b_terminal[0].stage is ProgressStage.COMPLETED

            # And the historical race's exact symptom -- a `failed`
            # event ever observed for B before B's own `completed` --
            # must never happen.
            assert "b failed" not in log
            assert log.index("b started") < log.index("b completed")

            _unsubscribe_recorder(event_bus, recorder)
            assert _progress_subscription_count(event_bus) == 0

    def test_a_and_b_both_fail_concurrently_without_cross_contamination(
        self,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        recorder = ProgressLifecycleRecorder(event_bus)
        log: list[str] = []
        log_lock = threading.Lock()
        barrier = threading.Barrier(2)

        tool_manager_a = ToolManager(event_bus=event_bus, logger=logger)
        tool_manager_b = ToolManager(event_bus=event_bus, logger=logger)

        progress_a = ProgressReporter(event_bus, "concurrent_failure.a")
        driver_a = _BarrierGatedDriver(
            progress_reporter=progress_a,
            barrier=barrier,
            delay_seconds=0.02,
            should_fail=True,
            tag="a",
            log=log,
            log_lock=log_lock,
        )
        tool_manager_a.register(_make_tool(id="concurrent_failure.a"), driver_a)

        progress_b = ProgressReporter(event_bus, "concurrent_failure.b")
        driver_b = _BarrierGatedDriver(
            progress_reporter=progress_b,
            barrier=barrier,
            delay_seconds=0.05,
            should_fail=True,
            tag="b",
            log=log,
            log_lock=log_lock,
        )
        tool_manager_b.register(_make_tool(id="concurrent_failure.b"), driver_b)

        results: dict[str, Any] = {}

        def _run_a() -> None:
            try:
                tool_manager_a.execute("concurrent_failure.a", ToolRequest())

            except Exception as ex:
                results["a"] = ex

        def _run_b() -> None:
            try:
                tool_manager_b.execute("concurrent_failure.b", ToolRequest())

            except Exception as ex:
                results["b"] = ex

        thread_a = threading.Thread(target=_run_a)
        thread_b = threading.Thread(target=_run_b)
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=5.0)
        thread_b.join(timeout=5.0)

        assert isinstance(results["a"], ToolExecutionError)
        assert isinstance(results["b"], ToolExecutionError)

        recorder.assert_every_started_has_exactly_one_terminal()

        # Each tool must receive exactly one `failed()`, carrying its
        # *own* exception message -- never the other tool's.
        a_terminal = recorder.terminal_events[progress_a.progress_id]
        assert len(a_terminal) == 1
        assert a_terminal[0].stage is ProgressStage.FAILED
        assert "a tool failed" in str(a_terminal[0].message)
        assert "b tool failed" not in str(a_terminal[0].message)

        b_terminal = recorder.terminal_events[progress_b.progress_id]
        assert len(b_terminal) == 1
        assert b_terminal[0].stage is ProgressStage.FAILED
        assert "b tool failed" in str(b_terminal[0].message)
        assert "a tool failed" not in str(b_terminal[0].message)

        _unsubscribe_recorder(event_bus, recorder)
        assert _progress_subscription_count(event_bus) == 0


class TestOriginalExceptionPreservation:
    """
    Robustness: if the guard's own cleanup mechanism
    (`ToolManager._fail_unterminated_progress()`) itself raises, the
    *original* driver exception must still be what ultimately
    propagates -- mirroring `CapabilityExecutor.execute()`'s existing
    "log and continue, never let a best-effort side channel mask the
    real failure" pattern
    (`parika/core/capability_executor/capability_executor.py`).
    """

    def test_cleanup_failure_does_not_mask_the_original_driver_exception(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _broken_cleanup(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("cleanup itself is broken")

        monkeypatch.setattr(
            tool_manager,
            "_fail_unterminated_progress",
            _broken_cleanup,
        )

        progress = ProgressReporter(event_bus, "example.generate")
        original_error = RuntimeError("perform_operation() failed.")
        driver = _FutureNaiveDriver(progress_reporter=progress, should_fail=True)
        tool = _make_tool()
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError) as excinfo:
            tool_manager.execute(tool.id, ToolRequest())

        # The original driver exception, not the cleanup mechanism's
        # own `RuntimeError`, must be what `ToolExecutionError.__cause__`
        # carries.
        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert str(excinfo.value.__cause__) == str(original_error)

    def test_cleanup_failure_still_unsubscribes_from_the_event_bus(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _broken_cleanup(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("cleanup itself is broken")

        monkeypatch.setattr(
            tool_manager,
            "_fail_unterminated_progress",
            _broken_cleanup,
        )

        progress = ProgressReporter(event_bus, "example.generate")
        driver = _FutureNaiveDriver(progress_reporter=progress, should_fail=True)
        tool = _make_tool()
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(tool.id, ToolRequest())

        assert _progress_subscription_count(event_bus) == 0
