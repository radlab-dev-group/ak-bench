# Implement a restartable event-time engine

Complete `WindowIndex`, `Changelog` and `Processor` in `src/streamforge/`.
Read the seed README in full: it defines source ordering, event identity,
watermarks, idleness, window boundaries, lateness, output and checkpoints.

The infrastructure is working, but this is a multi-module implementation:
window assignment and eviction, output reconciliation and durable coordination
must agree. A late event can bridge two already emitted sessions. Retract both
old results, merge their exact aggregates, and emit the merged result only if
it is closed. If its end moves past the watermark it remains live and silent.

Implement fixed, non-divisible sliding and transitively merged session windows
for negative as well as positive integer event times. Track all source offsets
and global identities, preserve atomic rejection, and keep duplicate retries
from changing either aggregates or the late side output.

Checkpoints must resume in a fresh interpreter with the same output sequence,
source fencing, side output and live state as uninterrupted processing. Test
the interactions with finalization and partition reactivation, not just an
individual window's arithmetic. The evaluator includes independent batch-model
comparisons and generated multi-stage traces with deterministic seeds.

Use only the standard library. Keep the public signatures and the working
infrastructure intact. Repository tests cover infrastructure; public task tests
illustrate the missing behavior. Hidden tests remain outside your workspace.
