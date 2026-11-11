# Decouple the order service from the bus with events

`OrderService` in `src/eventbus/service.py` publishes raw dicts on a
concrete `EventBus`. Decouple them without changing the behaviour:

- Create `src/eventbus/events.py` with an `OrderPlaced` dataclass:
  `order_id: int` and `total: int`.
- `OrderService` must accept any publisher: an object with a
  `publish(event)` method. `OrderService(publisher)` uses it;
  `OrderService()` with no argument still works, publishing on a
  default `EventBus`. `place_order` publishes an `OrderPlaced` event
  and keeps its exact signature and results.

The repository's own test suite pins the behaviour and must stay
green.

## What to check

- `OrderPlaced` exists with the fields above.
- A test double publisher (an object with a `publish` method that
  records events) receives an `OrderPlaced` with the right id and
  total when an order is placed.
- `OrderService()` with no argument still works as before.

## Boundaries

- Do not change the public API of the `eventbus` package.
- Do not modify the repository test suite under `tests/`.
- Do not change the pricing.
