# ADR-0001: Logical time and a fixed phase order per tick

Status: accepted. Supersedes: nothing. Referenced by: `SPEC.md` 1.1–1.2,
`tidewater.clock`, `tidewater.cluster`.

## Context

The first prototype of the simulator ran each node on a thread with
`time.sleep`-based election timers and a queue for the network. It found
bugs — and could not reproduce any of them. A run that showed two leaders
in one term could not be re-run; the log was the only evidence, and the
log had no total order. Every attempt to narrow the cause changed the
timing enough to make the symptom go away.

We needed three properties at once: a run is a pure function of its
inputs; two people running the same inputs see the same output byte for
byte; and any event in a run can be named by a small number so that a bug
report can say "at tick 2145".

## Decision

1. The only clock is an integer **tick**. Nothing in the package reads
   `time`, sleeps, or spawns a thread.
2. One tick is one call of `Cluster.step()` and its phases run in a fixed,
   documented order: schedule actions, pending proposals, due deliveries,
   node ticks, outbox drain, invariants, clock advance (`SPEC.md` 1.2).
3. Within a phase, iteration is in a documented order: actions in file
   order, deliveries in `(deliver_at, seq)`, nodes in id order.
4. A message sent at tick `t` is never delivered at tick `t`
   (`min_delay >= 1`), so a node cannot observe its own send within the
   tick that produced it.
5. Each node has its own `NodeClock` with an integer rate and offset, so
   clock skew is a first-class, deterministic input rather than an artefact
   of thread scheduling.

## Alternatives considered

* **Event-driven simulation with a single priority queue** of all events
  (timeouts, deliveries, actions) ordered by time. Cleaner in theory; in
  practice the order of equal-time events becomes a function of heap
  internals and insertion history, and a reader cannot predict it. We kept
  the priority queue for the network only, where the insertion order is
  already deterministic, and made the tick loop explicit.
* **Floating-point time.** Rejected: rounding makes "the same time" a
  judgement call, and the trace needs to print time without ambiguity.
* **Threads with a deterministic scheduler.** Rejected: large, and the
  thing we actually want from threads — concurrency — is exactly what
  makes bugs irreproducible.

## Consequences

* Two runs with the same schedule, seed and code produce identical traces.
  `tests/test_cluster.py::test_same_seed_same_trace_different_seed_different_trace`
  pins this.
* Changing the phase order changes every trace in the corpus. It is a
  legitimate change, but it is digest-breaking and follows the runbook.
* Some real-world behaviours are approximated. A reply to a message takes
  at least one tick; a node that crashes and restarts in the same tick is
  not expressible (restart is a separate action at a later tick).
* Skew is coarse: integer rates only. A node that runs 10% fast is not
  expressible; one that runs twice as fast is. This has been sufficient for
  every incident so far, because the interesting behaviours appear at
  rates of 2–4 (`docs/incidents/INC-0007`).
