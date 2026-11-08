---
id: INC-2912
severity: high
module: recovery
kind: a measurement we trusted
tags: protocol, replay
---

# INC-2912: fewer skipped records

The open-time report counts how many records the replay skipped, and the
inclusive window changed that count in a way that looked like an
improvement: fewer records skipped on open, and an open that got faster,
because the records it stopped skipping were records the image already held.
The measurement was trusted for three weeks. A skipped record is a record
the image already contains, and the count is a measure of how much work the
image saved, not of how much work the open did. A window that skips fewer
records is not a window that did less work; it is a window that re-did work
the image had done, and the only place that shows is in a value that is
derived from a previous value of the same key, which is a counter, which is
why the first symptom was a counter that advanced by two and the last was a
measurement nobody argued with.
