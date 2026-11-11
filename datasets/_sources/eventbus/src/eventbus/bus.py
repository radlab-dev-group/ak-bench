"""A tiny synchronous event bus."""

from __future__ import annotations

from typing import Any, Callable


class EventBus:
    """Delivers each published event to its subscribers, in order."""

    def __init__(self) -> None:
        self._subscribers: dict[type, list[Callable[[Any], None]]] = {}

    def subscribe(self, event_type: type, handler: Callable[[Any], None]) -> None:
        """Call ``handler`` for every published ``event_type``."""
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event: Any) -> None:
        """Deliver ``event`` to the subscribers of its type."""
        for handler in self._subscribers.get(type(event), []):
            handler(event)
