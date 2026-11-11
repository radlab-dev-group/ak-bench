# eventbus

A tiny order service publishing events on a bus. It is a benchmark
fixture for AK-Bench. The service is coupled directly to the bus on
purpose: the architecture task is to decouple them with events and a
publisher interface.

Run the suite with `pytest`.
