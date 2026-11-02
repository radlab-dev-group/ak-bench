# Repair durable queue recovery

WALQueue's ordinary live operations work, and its repository tests are green.
Production traces nevertheless show lost tasks, duplicate work and stale
acknowledgments after compaction or an interrupted write followed by restart.
The regression concerns the protocol connecting snapshots, WAL replay and
recovered queue state. Follow that protocol across modules before fixing it.

Read the seed README for the exact durable-state, frame, publication,
idempotency and generation-fencing rules. Preserve all of them. In particular,
complete acknowledged work must survive, terminal tasks and original request
identities must remain terminal, and a worker holding an old generation must
never acknowledge a replacement reservation, including after restart.

Use the existing deterministic crash hooks to reproduce failures. Discard the
Queue after a simulated crash and open it again; do not continue using an
object whose append was interrupted. A valid complete frame may survive a
call that did not return. A torn final frame must not erase preceding complete
transactions. Recovery must remain correct through a second restart and a
subsequent append or compaction.

CURRENT is the durable publication decision. Old WAL segments can coexist
with a published snapshot, and unpublished snapshot files can coexist with
an older CURRENT. Treat those states according to the documented protocol.
Avoid changing the disk format, disabling validation or bypassing errors.

The evaluator checks cross-module crash scenarios, transaction atomicity,
corruption handling, restart in a fresh interpreter and generated traces
against an independent in-memory queue model. Keep the public API and the
existing tests intact. Standard library only.
