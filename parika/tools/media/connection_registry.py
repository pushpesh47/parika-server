"""
PARIKA Media Tool - Connection Registry

`MediaConnectionRegistry` is the small, new realtime-transport
abstraction this Capability requires -
`docs/architecture/adr/0004-media-capability.md`'s "WebSocket/
realtime transport" decision explains why: PARIKA's only existing
WebSocket route (`parika/api/ws/chat.py`) is chat-specific, buffers
every outgoing message inside its own single receive loop, and keeps
no registry of open connections at all - there is no existing
mechanism a synchronous Tool driver could use to push an unsolicited
message to an open socket. This registry is the minimal addition that
closes exactly that gap, without duplicating or modifying `ws/chat.py`.

**Why this is non-blocking (see the Media task's own "Non-Blocking
Requirement"):** every PARIKA Core component, including
`ToolManager`/`Brain`, is synchronous by design (confirmed by this
increment's own architecture audit - `TaskManager.execute()` itself
blocks on `CapabilityExecutor.execute()`). `MediaToolDriver.execute()`
therefore also runs synchronously, on whatever thread/task is already
processing the request (e.g. the chat WebSocket's own event-loop
task). `dispatch()` below never awaits, never blocks on a Web Client
actually receiving or acting on a command, and never waits for
`asyncio.Queue.put()` to be consumed - it only calls
`loop.call_soon_threadsafe(...)`, which schedules delivery and returns
immediately, regardless of whether the target connection's own send
loop is busy, slow, or has not run yet. Actual delivery happens later,
on the Media WebSocket connection's own event-loop task
(`parika/api/ws/media.py`), fully decoupled from the calling thread.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from threading import RLock
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class _MediaConnection:
    """
    One connected Web Client's delivery handle.

    `ready` is `False` from the moment the WebSocket connects until
    that connection sends `{"type": "media.ready"}` (see
    `MediaConnectionRegistry.mark_ready()`) - a connection being open
    is not the same thing as that Web Client actually being ready to
    receive/act on a media command (see this class's own
    `MediaConnectionRegistry.dispatch()` docstring).
    """

    loop: asyncio.AbstractEventLoop
    outbound: "asyncio.Queue[Mapping[str, Any]]"
    capabilities: frozenset[str]
    ready: bool = False


class MediaCommandDispatcher(Protocol):
    """
    Structural contract `MediaToolDriver` depends on - satisfied by
    `MediaConnectionRegistry` in production and by a plain fake in
    tests, exactly like `ToolDriver` is a structural `Protocol`
    elsewhere in PARIKA.
    """

    def dispatch(self, message: Mapping[str, Any]) -> bool: ...

    def is_connected(self) -> bool: ...


class MediaConnectionRegistry:
    """
    Thread-safe registry of connected Media WebSocket clients, and the
    single point `MediaToolDriver` dispatches `media.*` commands
    through.

    Constructed once at the composition root and shared, via
    `ServiceContainer`, between `parika/api/ws/media.py` (which
    registers/unregisters connections) and `MediaToolDriver` (which
    only ever calls `dispatch()`/`is_connected()`) - the same shared-
    singleton pattern as `MediaStateStore`.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._connections: dict[str, _MediaConnection] = {}

    def register(
        self,
        client_id: str,
        *,
        loop: asyncio.AbstractEventLoop,
        outbound: "asyncio.Queue[Mapping[str, Any]]",
        capabilities: frozenset[str] = frozenset(),
    ) -> None:
        """
        Register a newly connected Web Client's delivery handle.

        The connection starts out *not* media-ready (see
        `_MediaConnection.ready`) - `mark_ready()` below is what
        `parika/api/ws/media.py` calls once this connection actually
        sends `{"type": "media.ready"}`.
        """

        with self._lock:
            self._connections[client_id] = _MediaConnection(
                loop=loop, outbound=outbound, capabilities=capabilities
            )

    def mark_ready(self, client_id: str) -> None:
        """
        Mark a connection as media-ready, following its own
        `{"type": "media.ready"}` handshake. A no-op if `client_id` is
        unknown (e.g. it already disconnected).
        """

        with self._lock:
            connection = self._connections.get(client_id)

            if connection is not None:
                self._connections[client_id] = replace(connection, ready=True)

    def unregister(self, client_id: str) -> None:
        """Remove a disconnected Web Client. A no-op if unknown."""

        with self._lock:
            self._connections.pop(client_id, None)

    def is_connected(self) -> bool:
        """
        Whether at least one Web Client is currently connected -
        connected, not necessarily media-ready yet (see `dispatch()`
        for the readiness-gated check). This is what
        `MediaState.client_connected` reflects.
        """

        with self._lock:
            return bool(self._connections)

    def connection_count(self) -> int:
        with self._lock:
            return len(self._connections)

    def dispatch(self, message: Mapping[str, Any]) -> bool:
        """
        Schedule delivery of `message` to every media-ready connected
        Web Client - a connection that has not yet sent
        `{"type": "media.ready"}` (see `mark_ready()`) is connected
        but not dispatchable, and is skipped here exactly as if it
        were not connected at all.

        Never blocks on delivery - see this module's own docstring.
        For each ready connection this only calls
        `loop.call_soon_threadsafe(outbound.put_nowait, message)`,
        which schedules the enqueue and returns immediately.

        A connection snapshotted as ready above can still disconnect,
        with its event loop closed, before this method reaches it -
        `call_soon_threadsafe()` on an already-closed loop raises
        `RuntimeError`. That is expected, not exceptional, for a
        realtime transport: this method catches it per-connection and
        treats that one connection as unavailable for this dispatch,
        without raising and without affecting any other connection's
        delivery. It never unregisters the stale connection itself -
        connection lifecycle stays owned by the WebSocket layer
        (`parika/api/ws/media.py`), which will call `unregister()` once
        it observes the disconnect.

        Returns:
            `True` if delivery was successfully *scheduled* to at
            least one ready Web Client; `False` if no ready Web
            Client could have the command scheduled (either because
            none are ready, or every ready connection's loop was
            already closed). This is only a scheduling outcome - it
            does not mean any Web Client actually received or acted
            on the message (see `driver.py`, which reports `True` as
            `"status": "dispatched"` and `False` as `"status":
            "unavailable"`).
        """

        with self._lock:
            connections = tuple(
                connection
                for connection in self._connections.values()
                if connection.ready
            )

        scheduled = False

        for connection in connections:
            try:
                connection.loop.call_soon_threadsafe(
                    connection.outbound.put_nowait, message
                )
            except RuntimeError:
                # The connection's own event loop is already closed -
                # this Web Client disconnected between the snapshot
                # above and this call. Treat only this connection as
                # unavailable for this dispatch; do not let one stale
                # connection fail delivery to the others, and do not
                # raise out of the Media Tool invocation over it.
                continue

            scheduled = True

        return scheduled
