---
id: INC-2905
severity: high
module: rebalance
kind: the rule behind a rule
tags: protocol, read-first
---

# INC-2905: the move that published first

Five steps, and the order is the whole feature: build, work out what moves,
copy it and bring the destination up to date, announce, then let go. The
cluster we debugged announced before it copied, which is a period in which a
write lands on a machine with no key, and then let go before it copied, which
is a key that is simply not there. Both faults pass every single-write test
in existence, because a single write does not straddle an announcement. The
audit trail is the report the run leaves behind; if it shows an announcement
before a copy finished, the run is wrong and no amount of green afterwards
saves it.
