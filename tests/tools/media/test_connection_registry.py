"""
Unit tests for `MediaConnectionRegistry` - the WebSocket connection
registry `MediaToolDriver` dispatches `media.*` commands through.

`TestNonBlockingDispatch` is the deterministic proof (see the Media
task's own "Non-Blocking Requirement" and
`docs/guides/Testing.md`'s "synchronize on a threading.Event" pattern,
also used by `tests/core/scheduler/test_scheduler.py`) that
`dispatch()` never blocks the calling thread waiting for a Web
Client's own event-loop thread to actually process a scheduled
delivery - the mechanism `MediaToolDriver.execute()` relies on to stay
non-blocking with respect to the rest of PARIKA's synchronous request
processing.
"""

from __future__ import annotations

import asyncio
import threading
import time

from parika.tools.media.connection_registry import MediaConnectionRegistry


class TestMediaConnectionRegistry:
    def test_dispatch_without_any_connection_returns_false(self) -> None:
        registry = MediaConnectionRegistry()

        assert registry.is_connected() is False
        assert registry.dispatch({"type": "media.pause"}) is False

    def test_register_alone_is_connected_but_not_ready_for_dispatch(self) -> None:
        """
        A newly registered connection is connected (see
        `is_connected()`) but must not receive dispatched commands
        until it sends `{"type": "media.ready"}` - `mark_ready()`
        below.
        """

        loop = asyncio.new_event_loop()
        outbound: "asyncio.Queue" = asyncio.Queue()
        registry = MediaConnectionRegistry()

        try:
            registry.register("client-1", loop=loop, outbound=outbound)

            assert registry.is_connected() is True
            assert registry.connection_count() == 1
            assert registry.dispatch({"type": "media.play"}) is False

            loop.run_until_complete(asyncio.sleep(0))
            assert outbound.empty()

        finally:
            loop.close()

    def test_mark_ready_makes_a_connection_dispatchable(self) -> None:
        loop = asyncio.new_event_loop()
        outbound: "asyncio.Queue" = asyncio.Queue()
        registry = MediaConnectionRegistry()

        try:
            registry.register("client-1", loop=loop, outbound=outbound)
            registry.mark_ready("client-1")

            assert registry.dispatch({"type": "media.play"}) is True

            # `call_soon_threadsafe` callbacks only run once the loop
            # actually processes an iteration.
            loop.run_until_complete(asyncio.sleep(0))

            assert outbound.get_nowait() == {"type": "media.play"}

        finally:
            loop.close()

    def test_mark_ready_of_an_unknown_client_is_a_no_op(self) -> None:
        registry = MediaConnectionRegistry()
        registry.mark_ready("never-registered")  # must not raise

    def test_dispatch_enqueues_only_to_ready_clients(self) -> None:
        loop = asyncio.new_event_loop()
        outbound_a: "asyncio.Queue" = asyncio.Queue()
        outbound_b: "asyncio.Queue" = asyncio.Queue()
        registry = MediaConnectionRegistry()

        try:
            registry.register("client-a", loop=loop, outbound=outbound_a)
            registry.register("client-b", loop=loop, outbound=outbound_b)
            registry.mark_ready("client-a")

            assert registry.connection_count() == 2
            assert registry.dispatch({"type": "media.pause"}) is True

            loop.run_until_complete(asyncio.sleep(0))

            assert outbound_a.get_nowait() == {"type": "media.pause"}
            assert outbound_b.empty()

        finally:
            loop.close()

    def test_dispatch_enqueues_to_every_ready_client(self) -> None:
        loop = asyncio.new_event_loop()
        outbound_a: "asyncio.Queue" = asyncio.Queue()
        outbound_b: "asyncio.Queue" = asyncio.Queue()
        registry = MediaConnectionRegistry()

        try:
            registry.register("client-a", loop=loop, outbound=outbound_a)
            registry.register("client-b", loop=loop, outbound=outbound_b)
            registry.mark_ready("client-a")
            registry.mark_ready("client-b")

            assert registry.connection_count() == 2
            assert registry.dispatch({"type": "media.pause"}) is True

            loop.run_until_complete(asyncio.sleep(0))

            assert outbound_a.get_nowait() == {"type": "media.pause"}
            assert outbound_b.get_nowait() == {"type": "media.pause"}

        finally:
            loop.close()

    def test_unregister_removes_the_connection_and_its_readiness(self) -> None:
        loop = asyncio.new_event_loop()
        outbound: "asyncio.Queue" = asyncio.Queue()
        registry = MediaConnectionRegistry()

        try:
            registry.register("client-1", loop=loop, outbound=outbound)
            registry.mark_ready("client-1")
            registry.unregister("client-1")

            assert registry.is_connected() is False
            assert registry.connection_count() == 0
            assert registry.dispatch({"type": "media.pause"}) is False

            # Re-registering the same client_id starts not-ready again.
            registry.register("client-1", loop=loop, outbound=outbound)
            assert registry.dispatch({"type": "media.pause"}) is False

        finally:
            loop.close()

    def test_unregister_of_an_unknown_client_is_a_no_op(self) -> None:
        registry = MediaConnectionRegistry()
        registry.unregister("never-registered")  # must not raise

    def test_dispatch_skips_a_ready_connection_whose_loop_is_already_closed(
        self,
    ) -> None:
        """
        Deterministic reproduction of the dispatch race: a Web Client
        can be snapshotted as ready and then disconnect - its event
        loop closed - before `dispatch()` reaches it.
        `loop.call_soon_threadsafe()` on an already-closed loop raises
        `RuntimeError`; `dispatch()` must swallow that per-connection,
        not propagate it, and must not report that connection as
        having had delivery scheduled.
        """

        stale_loop = asyncio.new_event_loop()
        stale_loop.close()  # closed *before* dispatch() ever touches it
        stale_outbound: "asyncio.Queue" = asyncio.Queue()

        registry = MediaConnectionRegistry()
        registry.register("stale-client", loop=stale_loop, outbound=stale_outbound)
        registry.mark_ready("stale-client")

        # Must not raise, even though the only ready connection's loop
        # is closed, and must report no successful scheduling.
        assert registry.dispatch({"type": "media.play"}) is False

        # The stale connection is left in place - dispatch() does not
        # unregister it; that stays owned by the WebSocket layer.
        assert registry.connection_count() == 1

    def test_dispatch_still_reaches_other_ready_clients_when_one_loop_is_closed(
        self,
    ) -> None:
        """
        One stale/closed connection must not block delivery scheduling
        to the other, still-live ready connections.
        """

        stale_loop = asyncio.new_event_loop()
        stale_loop.close()
        stale_outbound: "asyncio.Queue" = asyncio.Queue()

        live_loop = asyncio.new_event_loop()
        live_outbound: "asyncio.Queue" = asyncio.Queue()

        registry = MediaConnectionRegistry()

        try:
            registry.register(
                "stale-client", loop=stale_loop, outbound=stale_outbound
            )
            registry.register("live-client", loop=live_loop, outbound=live_outbound)
            registry.mark_ready("stale-client")
            registry.mark_ready("live-client")

            assert registry.dispatch({"type": "media.pause"}) is True

            live_loop.run_until_complete(asyncio.sleep(0))
            assert live_outbound.get_nowait() == {"type": "media.pause"}
            assert stale_outbound.empty()

        finally:
            live_loop.close()


class TestNonBlockingDispatch:
    def test_dispatch_returns_immediately_even_while_the_target_loop_is_busy(
        self,
    ) -> None:
        """
        Registers a connection whose event-loop thread is
        deliberately monopolized by a tight, non-yielding loop (so it
        cannot process any scheduled callback yet); `dispatch()` from
        this test's own thread must still return almost immediately,
        proving it never waits for the target loop to actually
        process the scheduled delivery.
        """

        started = threading.Event()
        release = threading.Event()
        loop = asyncio.new_event_loop()

        async def _busy() -> None:
            started.set()
            deadline = time.perf_counter() + 2.0

            # Deliberately never `await` inside this loop: the event
            # loop thread is fully monopolized until `release` is set,
            # simulating a Web Client connection whose send loop
            # cannot run yet.
            while not release.is_set() and time.perf_counter() < deadline:
                pass

        def _run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_busy())

        thread = threading.Thread(target=_run_loop, daemon=True)
        thread.start()

        assert started.wait(timeout=2.0), "busy loop never started"

        outbound: "asyncio.Queue" = asyncio.Queue()
        registry = MediaConnectionRegistry()
        registry.register("busy-client", loop=loop, outbound=outbound)
        registry.mark_ready("busy-client")

        start_time = time.perf_counter()
        dispatched = registry.dispatch({"type": "media.play"})
        elapsed_seconds = time.perf_counter() - start_time

        assert dispatched is True
        assert elapsed_seconds < 0.5, (
            "dispatch() must never block on a busy consumer loop; took "
            f"{elapsed_seconds:.3f}s"
        )

        release.set()
        thread.join(timeout=3.0)
        assert not thread.is_alive()
