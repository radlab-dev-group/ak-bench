"""The decoupling, proven: typed events plus preserved behaviour.

These tests fail on the base commit (the target module does not exist)
and pass once the service depends on a publisher interface.
"""

from __future__ import annotations

from dataclasses import is_dataclass

from eventbus import OrderService
from eventbus.bus import EventBus
from eventbus.events import OrderPlaced


class FakePublisher:
    """A test double: records every published event."""

    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def test_order_placed_is_a_dataclass_with_id_and_total():
    assert is_dataclass(OrderPlaced)
    event = OrderPlaced(order_id=3, total=1500)
    assert event.order_id == 3
    assert event.total == 1500


def test_the_service_publishes_typed_events_to_any_publisher():
    publisher = FakePublisher()
    service = OrderService(publisher)
    service.place_order([(1000, 2)])
    service.place_order([(500, 1)])
    assert publisher.events == [
        OrderPlaced(order_id=1, total=2000),
        OrderPlaced(order_id=2, total=500),
    ]


def test_the_bus_delivers_typed_events():
    bus = EventBus()
    seen = []
    bus.subscribe(OrderPlaced, seen.append)
    service = OrderService(bus)
    service.place_order([(1000, 2)])
    assert seen == [OrderPlaced(order_id=1, total=2000)]


def test_the_default_service_behaviour_is_unchanged():
    service = OrderService()
    assert service.place_order([(1000, 2)]) == {"order_id": 1, "total": 2000}
    assert service.place_order([(500, 1)]) == {"order_id": 2, "total": 500}
