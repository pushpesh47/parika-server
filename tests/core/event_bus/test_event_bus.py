"""
Unit tests for EventBus.
"""

from __future__ import annotations

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[object] = []

    def __call__(self, payload: object) -> None:
        self.received.append(payload)


class _RaisingSubscriber:
    def __call__(self, payload: object) -> None:
        raise RuntimeError("subscriber boom")


# ---------------------------------------------------------------------
# subscribe() / publish()
# ---------------------------------------------------------------------


class TestSubscribeAndPublish:
    def test_subscriber_receives_published_payload(
        self,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("task.created", subscriber)

        event_bus.publish("task.created", "payload")

        assert subscriber.received == ["payload"]

    def test_publish_without_payload_defaults_to_none(
        self,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("task.created", subscriber)

        event_bus.publish("task.created")

        assert subscriber.received == [None]

    def test_multiple_subscribers_invoked_in_registration_order(
        self,
        event_bus: EventBus,
    ) -> None:
        calls: list[str] = []

        event_bus.subscribe("event", lambda payload: calls.append("first"))
        event_bus.subscribe("event", lambda payload: calls.append("second"))

        event_bus.publish("event")

        assert calls == ["first", "second"]

    def test_publish_with_no_subscribers_is_a_no_op(
        self,
        event_bus: EventBus,
    ) -> None:
        # Should not raise even though nothing is subscribed.
        event_bus.publish("unknown.event", "payload")

    def test_subscribers_are_isolated_per_event_name(
        self,
        event_bus: EventBus,
    ) -> None:
        a_subscriber = RecordingSubscriber()
        b_subscriber = RecordingSubscriber()

        event_bus.subscribe("event.a", a_subscriber)
        event_bus.subscribe("event.b", b_subscriber)

        event_bus.publish("event.a", "payload")

        assert a_subscriber.received == ["payload"]
        assert b_subscriber.received == []

    def test_duplicate_subscription_is_ignored(
        self,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()

        event_bus.subscribe("event", subscriber)
        event_bus.subscribe("event", subscriber)

        event_bus.publish("event", "payload")

        assert subscriber.received == ["payload"]

    def test_exception_in_one_subscriber_does_not_prevent_others(
        self,
        event_bus: EventBus,
    ) -> None:
        after = RecordingSubscriber()

        event_bus.subscribe("event", _RaisingSubscriber())
        event_bus.subscribe("event", after)

        # Should not raise despite the first subscriber failing.
        event_bus.publish("event", "payload")

        assert after.received == ["payload"]


# ---------------------------------------------------------------------
# unsubscribe()
# ---------------------------------------------------------------------


class TestUnsubscribe:
    def test_unsubscribe_removes_subscriber(
        self,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("event", subscriber)

        event_bus.unsubscribe("event", subscriber)
        event_bus.publish("event", "payload")

        assert subscriber.received == []

    def test_unsubscribe_unknown_event_is_a_no_op(
        self,
        event_bus: EventBus,
    ) -> None:
        # Should not raise.
        event_bus.unsubscribe("unknown.event", RecordingSubscriber())

    def test_unsubscribe_unknown_subscriber_is_a_no_op(
        self,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("event", subscriber)

        # Should not raise even though this subscriber was never
        # registered.
        event_bus.unsubscribe("event", RecordingSubscriber())

        event_bus.publish("event", "payload")
        assert subscriber.received == ["payload"]

    def test_unsubscribing_last_subscriber_cleans_up_event_entry(
        self,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("event", subscriber)
        event_bus.unsubscribe("event", subscriber)

        # Internal state should be fully cleaned up; re-subscribing and
        # publishing should behave exactly as if the event were new.
        other = RecordingSubscriber()
        event_bus.subscribe("event", other)
        event_bus.publish("event", "payload")

        assert other.received == ["payload"]


# ---------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------


class TestConstruction:
    def test_requires_a_logger(self, logger: Logger) -> None:
        event_bus = EventBus(logger)

        # Should not raise when publishing immediately after
        # construction.
        event_bus.publish("event", "payload")
