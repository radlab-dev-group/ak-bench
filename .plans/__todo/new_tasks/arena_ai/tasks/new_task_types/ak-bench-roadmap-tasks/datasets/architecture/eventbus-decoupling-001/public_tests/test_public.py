"""The decoupling, in miniature: typed events through any publisher."""

from __future__ import annotations

from eventbus import OrderService
from eventbus.events import OrderPlaced


class FakePublisher:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def test_a_fake_publisher_receives_a_typed_event():
    publisher = FakePublisher()
    service = OrderService(publisher)
    assert service.place_order([(1000, 2)]) == {"order_id": 1, "total": 2000}
    assert publisher.events == [OrderPlaced(order_id=1, total=2000)]


def test_the_default_service_still_works():
    service = OrderService()
    assert service.place_order([(500, 1)]) == {"order_id": 1, "total": 500}
