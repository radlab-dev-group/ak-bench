# shopcore

A tiny order service: `OrderService.place_order(items)` prices an
order, stores it, and notifies the customer, all in one class. It is
a benchmark fixture for AK-Bench. The tangled responsibilities are
deliberate: the architecture task is to split them into layers.

Run the suite with `pytest`.
