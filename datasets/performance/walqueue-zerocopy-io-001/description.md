# A queue whose cost grows with everything it has ever done

Put a thousand tasks and then put one more. The second put costs more than the
first, and the thousand-and-first costs more than the thousandth, because
`Queue._commit` does this before it writes anything:

1. `canonical(commands)` and straight back through `json.loads`, to normalise a
   handful of commands;
2. `self.state.clone()`, which is `restore(document())` — the whole queue
   serialised to JSON and rebuilt, every task, every idempotency key;
3. apply the commands to the clone;
4. open the active segment again, write one frame, `os.fsync` it.

Step 2 is the quadratic. It exists so that a transaction which fails validation
leaves the store untouched — which is a real requirement, `tests/test_queue.py`
checks it (`test_batch_validation_is_atomic`) — but paying for it with a full
serialisation of history is not the only way to have it.

## What to do

Make the write path cost what the write is. The candidates, in the order the
profile shows them:

- validation that does not clone the world to find out whether it could fail;
- the frame assembled once — `ADR-0004` allows a buffer, a `memoryview`, and an
  incremental `hashlib` over the pieces, as long as the bytes the digest covers
  are the same bytes it covers today;
- the segment opened once rather than once per transaction;
- the command list not put through JSON twice.

Measure with the queue itself; the hidden harness does the same thing against a
pristine copy of the seed, in the same process family, so what it compares is a
ratio:

```bash
python -c "
import sys, time, tempfile, pathlib
sys.path.insert(0, 'src'); from walqueue import Queue
d = pathlib.Path(tempfile.mkdtemp()); t = time.process_time(); q = Queue(d)
for i in range(400): q.put(f't{i}', {'n': i})
for i in range(0, 400, 2):
    (lease,) = q.reserve('w', now=i, lease_seconds=10); q.ack(lease, now=i)
print(f'{time.process_time() - t:.3f}s')"
```

## What must not change

**Durability, exactly.** `docs/adr/ADR-0004-a-sync-is-a-promise-per-transaction-not-per-append.md`
is the contract and it is short: a call that returns success has had its frame
synced; a frame is never split; a failed write leaves the journal exactly as it
was. A queue that never fsyncs is faster than any queue that does and is not the
same program — the hidden harness therefore runs your store against a crash at
every hook point in `journal.py` and `snapshot.py`
(`append.header`, `append.payload`, `append.frame`, `append.synced`,
`compact.rotated`, `compact.snapshot`, `compact.manifest`, `compact.pruned`) and
requires that what the client was told survives, and that nothing it was not
told about appears.

**The format.** A frame is a length prefix, canonical JSON, and a SHA-256 digest
(`ADR-0003`: only the newest segment may end in a torn frame). A store written
by the base commit must open after your change. `tests/` stays green and is not
yours to edit; `docs/incidents/` explains why three of these invariants are
written down at all.
