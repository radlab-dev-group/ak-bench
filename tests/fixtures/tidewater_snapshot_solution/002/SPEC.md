# Tidewater specification

Normative. `README.md` is a map; this is the contract. Every rule below is
implemented, except sections 6 and 7, which declare features that are not
(`src/tidewater/snapshot.py`, `src/tidewater/membership.py`). Where this
document and a module docstring disagree, this document is right; where this
document and a decision record under `docs/adr/` disagree, the decision
record is right and this document has a bug (`CONTRIBUTING.md`).

Section numbers are stable: code comments and incident reports cite them.

## 1. Time and determinism

1.1 The only clock is the **tick**, an integer owned by
`tidewater.clock.LogicalClock`. Nothing reads the wall clock, sleeps, or runs
on a thread. A run is a pure function of `(schedule, seed, code)`.

1.2 One tick is one call of `Cluster.step()`, whose phases run in this order
and no other:

1. schedule actions due at this tick, in file order;
2. pending client proposals, offered to the live leader of the highest term;
3. network deliveries due at this tick, in `(deliver_at, seq)` order, each
   handed to its destination node's `receive`;
4. every node's `tick`, in node-id order;
5. every node's outbox drained into the network, in node-id order;
6. the invariant monitor (section 10);
7. the clock advances by one.

A message delivered at tick `t` is answered at tick `t` (phase 5) and the
answer arrives no earlier than `t + min_delay`.

1.3 Each node has a **node clock** (`tidewater.clock.NodeClock`) with an
integer `rate >= 1` and an `offset >= 0`. Local time advances by `rate` per
global tick. Election timers, heartbeat timers and the leader lease (2.7)
are measured in local ticks. A schedule's `skew` action changes `rate` and
`offset` from that tick on; local time never jumps backwards.

1.4 **Randomness** comes only from `tidewater.rng.SeedTree`. The root seed
is the schedule's `seed` (or the `--seed` override). Child streams are
derived by SHA-256 over `(root, *labels)`; the two label sets in use are
`(node_id, "election")` — one per node — and `("network",)`. A draw on one
stream never affects another stream. Streams are `random.Random` instances;
the only methods used are `randrange`, `randint` and `random`.

1.5 **Network rules.** Every message is delayed by
`randint(min_delay, max_delay)` ticks drawn from the network stream at send
time; `min_delay >= 1`. A message whose source and destination cannot reach
each other at send time (partition, blocked link, either side down) is
dropped at send time with the reason traced. A random drop (`drop_rate`) is
decided at send time, after the reachability check, by one `random()` draw.
A duplicate (`dup_rate`) is decided by one further `random()` draw after a
successful send and is queued with its own extra delay
`randint(0, dup_extra_delay)`. Messages already in flight when a partition
is declared are still delivered. Messages in flight to a node that crashes
are dropped at delivery time. There is no separate reordering knob:
reordering is a consequence of independent delays.

1.6 **Node identity and order.** Node ids are strings; the schedule lists
them in sorted order, and every iteration over nodes in the simulator is in
that order.

## 2. Elections

2.1 **Terms.** Every node has a persistent `current_term`, starting at 0.
Every message carries the sender's term. A node that receives any message
with a term higher than its own first adopts that term, clears its vote,
becomes a follower, persists, and only then processes the message. A node
that receives a `RequestVote` or `AppendEntries` with a term lower than its
own rejects it, replying with its own term. Pre-votes (2.4) are the one
exception: they never change the receiver's term.

2.2 **Roles.** `follower`, `pre_candidate`, `candidate`, `leader`. A node
starts as a follower with a fresh election timer.

2.3 **The randomised election timeout.** `T = election_timeout` (schedule
option, default 50). Whenever the election timer is reset, the node draws

    timeout = T + stream.randrange(T)          # in [T, 2T)

from **its own** election stream and sets `deadline = local_now + timeout`.
The lower bound is inclusive, the upper bound exclusive, and the window
width equals `T`. The timer is reset at: node start; node restart; becoming
a follower for any reason; granting a real vote (not a pre-vote); accepting
or rejecting an `AppendEntries` from a leader whose term is at least the
node's own; starting a pre-vote; starting an election. Leaders have no
election timer. A node whose timer fires calls 2.4 (or 2.5 if `pre_vote`
is false or the configuration has one voter).

2.4 **Pre-vote.** A node whose timer fires becomes a `pre_candidate`,
resets its timer, counts itself, and sends
`RequestVote(term = current_term + 1, pre_vote = True, last_log_index,
last_log_term)` to every peer in the current configuration. It changes no
persistent state. A receiver grants a pre-vote if and only if all of:

* it is not a leader;
* `msg.term >= receiver.current_term`;
* it has not heard from a leader within the last `T` local ticks (2.7);
* the candidate's log is at least as up to date as its own (2.6).

The receiver replies `RequestVoteResponse(term = receiver.current_term,
granted, pre_vote = True)` and changes nothing. A pre-candidate that collects
pre-votes from a majority of the current configuration (itself included)
starts an election (2.5). A pre-candidate that receives a *denied* pre-vote
carrying a term higher than its own adopts that term and becomes a
follower. Granted pre-votes with a higher term are counted, not adopted.
Pre-vote responses received in any other role are ignored.

2.5 **Election.** The node increments `current_term`, votes for itself,
persists both, becomes a `candidate`, resets its timer, and sends
`RequestVote(term, pre_vote = False, last_log_index, last_log_term)` to every
peer. A single-voter configuration wins at once. A candidate that collects
votes from a majority of the current configuration becomes leader (2.8). A
candidate that receives `AppendEntries` with a term at least its own becomes
a follower of that leader. A candidate whose timer fires again starts a new
pre-vote (or election) for the next term.

2.6 **Granting a vote.** A receiver of a real `RequestVote` first applies
2.1. It then grants if and only if `voted_for` is empty or already equals
the candidate, and the candidate's log is **at least as up to date**: the
candidate's `last_log_term` is greater than the receiver's, or the terms are
equal and the candidate's `last_log_index` is at least the receiver's. A
granted vote is persisted and synced before the reply is placed in the
outbox, and resets the election timer. Denials are replied to with the
receiver's current term and the reason is traced
(`stale_term`, `already_voted`, `log_behind`).

2.7 **Leader lease (stickiness).** A non-leader records
`last_leader_contact = local_now` whenever it accepts or rejects an
`AppendEntries` from a leader with a term at least its own. While
`local_now - last_leader_contact < T` and `leader_id` is known, it denies
pre-votes with reason `leader_lease`. The lease does not affect real votes.

2.8 **Becoming leader.** The new leader sets `next_index[p] = last_index + 1`
and `match_index[p] = 0` for every peer, appends a **no-op entry** in its
own term, persists it, and sends `AppendEntries` to every peer at once. It
then sends `AppendEntries` to every peer whenever `heartbeat_interval` local
ticks have passed since the last broadcast (an empty `entries` is a
heartbeat). `heartbeat_interval * 3 <= T` is enforced by the schedule.

2.9 **Stepping down.** A leader or candidate that sees a higher term in any
message becomes a follower (2.1). A leader does not step down for lack of
contact with followers; a partitioned leader keeps its role until a message
with a higher term reaches it. Consequently proposals accepted by a
partitioned leader are appended to its log and are later truncated (3.3)
rather than committed — they are never acknowledged as committed, because
4.1 cannot be satisfied without a majority.

## 3. Log replication

3.1 **AppendEntries.** `AppendEntries(term, leader_id, prev_log_index,
prev_log_term, entries, leader_commit)`. For peer `p` the leader sends
`prev_log_index = next_index[p] - 1`, `prev_log_term = term_at(prev_log_index)`,
and `entries = log[next_index[p] : next_index[p] + max_entries_per_append]`.
Index 0 has term 0 and denotes the empty prefix. If `prev_log_index` is
below the leader's first retained index the leader sends a snapshot instead
(section 6, declared).

3.2 **Log matching check.** A follower accepts `AppendEntries` only if its
log contains an entry at `prev_log_index` with term `prev_log_term`
(`RaftLog.matches`). Index 0 always matches. The compacted boundary
(`base_index`, `base_term`) matches like an entry.

3.3 **Truncate only on conflict.** When the prefix matches, the follower
walks the incoming entries in order. An entry whose index is not in the log
is appended. An entry whose index is in the log with the **same term** is
left alone. The first entry whose index is in the log with a **different
term** causes the log to be truncated from that index; the entry and all
following entries are then appended. A follower never truncates on a
mismatched prefix, never truncates entries beyond what the incoming message
covers, and never truncates because an `AppendEntries` is "old": a delayed
or duplicated append whose entries are all already present changes nothing.

3.4 **Rejection and the conflict hint.** On a mismatched prefix the follower
replies `success = False` with `conflict_term = term_at(prev_log_index)` and
`conflict_index =` the first index of that term in its log; if it has no
entry at `prev_log_index`, it replies `conflict_index = last_index + 1,
conflict_term = 0`. The leader, on such a reply in its own term, sets
`next_index[p]` to: the index after its last entry of `conflict_term` if it
has entries of that term, otherwise `conflict_index`; clamped to at most
`next_index[p] - 1` and at least its first retained index. It resends at
once.

3.5 **Success.** On an accepted append the follower replies `success = True,
match_index = prev_log_index + len(entries)`. The leader sets
`match_index[p] = max(match_index[p], reply.match_index)` and
`next_index[p] = max(next_index[p], reply.match_index + 1)`, runs 4.1, and if
`next_index[p] <= last_index` sends the next batch at once.

3.6 **Persistence of appends.** A follower that appended or truncated
anything persists and syncs the log before placing its reply in the outbox.

## 4. Commit rules

4.1 **The current-term rule.** A leader sets `commit_index` to the largest
`N` such that `N > commit_index`, `log[N].term == current_term`, and
`match_index[q] >= N` for a majority of the **current configuration**
(counting itself with `match_index = last_index`). An entry from an earlier
term is never committed by counting replicas; it becomes committed only when
an entry of the current term above it does. This is why 2.8 appends a no-op.

4.2 **Majority of the configuration.** A majority is `size // 2 + 1` of the
voters in the node's current `Configuration`. Acknowledgements from nodes
outside the configuration are ignored. The number of nodes that *answered*
is irrelevant.

4.3 **Follower commit.** After an accepted append, if `leader_commit >
commit_index` the follower sets
`commit_index = min(leader_commit, prev_log_index + len(entries))` — never
past the last entry it knows it shares with the leader.

4.4 **Apply.** Every node applies entries in index order from
`last_applied + 1` through `commit_index` to its `KVStateMachine`,
immediately after any change to `commit_index`. No-op and configuration
entries advance `last_applied` without touching the map. Each apply is
traced with the state digest.

4.5 **Monotonicity.** `commit_index` never decreases while a node is up. It
is volatile and starts at 0 after a restart (5.4).

## 5. Persistence and the crash contract

5.1 **Durable state** is `current_term`, `voted_for`, the log (entries,
`base_index`, `base_term`), the snapshot record (section 6) and the voter
set. **Volatile state** is everything else: role, leader id, commit index,
applied state, `next_index`/`match_index`, vote tallies, timers, in-flight
transfers.

5.2 **Sync points.** A node calls `Storage.sync()` after: adopting a higher
term; voting for itself; granting a vote; appending or truncating entries on
the follower side; appending an entry as leader (no-op or proposal). In
every case the sync precedes the message that depends on the write being
placed in the outbox. A node never sends a reply that reflects state it has
not synced.

5.3 **Crash.** `Node.crash()` marks the node down, discards the volatile
state, clears its outbox, and calls `Storage.crash()`, which replaces the
volatile copy of persistent state with the last synced copy. Messages in
flight to the node are dropped at delivery; messages it would have sent are
not sent. A crashed node does not tick and does not receive.

5.4 **Restart.** `Node.restart()` reloads the log from storage, becomes a
follower in its persisted term with its persisted vote, resets the election
timer, sets `commit_index = 0`, and rebuilds the state machine by replaying
from index 1 as entries become committed again (once snapshots exist, from
the snapshot; section 6). `restarts` is incremented; the invariant monitor
uses it to allow the commit index reset.

5.5 **Sync policies** (`Storage.sync_policy`): `always` — every write is
durable immediately (default); `explicit` — writes become durable at
`sync()`; `never` — `sync()` is a no-op and a crash loses every write. The
last exists so a test can show that the contract matters
(`docs/incidents/INC-0003`).

## 6. Snapshots and log compaction — declared, not implemented

The seed runs with `compaction_threshold = 0`. Every entry point in
`src/tidewater/snapshot.py` raises `FeatureNotImplemented`. The following is
the acceptance contract.

6.1 **Trigger.** A node whose log holds at least `compaction_threshold`
entries and whose `last_applied` is above `base_index` takes a snapshot at
`last_applied` immediately after applying. Every node snapshots
independently; the leader does not coordinate.

6.2 **Record and order.** The snapshot record is
`SnapshotRecord(last_included_index = last_applied, last_included_term =
term_at(last_applied), state = state_machine.snapshot_bytes(), config =
voters in force at that index)`. The node saves and syncs the record
**before** compacting the log, then compacts, then saves and syncs the log.
A crash between the two leaves a longer log and a usable snapshot, never a
shorter log and no snapshot.

6.3 **Compaction.** `RaftLog.compact_to(last_included_index - keep_entries,
term)` where `keep_entries` (default 8) entries after the boundary are kept
so followers that are only slightly behind are served by `AppendEntries`.
The boundary never passes `last_applied`. After compaction `base_index` and
`base_term` are the boundary, `term_at(base_index) == base_term`, and the
log-matching check at the boundary behaves as for an entry (3.2).

6.4 **Transfer.** When `next_index[p] <= first_index` the leader sends
`InstallSnapshot(term, leader_id, last_included_index, last_included_term,
offset, data, done)` with `data` the bytes `[offset, offset + chunk_size)` of
the record's state and `done` true on the last chunk; chunks go in order,
one outstanding at a time. The follower replies
`InstallSnapshotResponse(term, follower_id, offset = next expected byte,
done)`. The leader continues from the follower's offset, not its own
counter.

6.5 **Install.** A follower buffers chunks in volatile memory. A chunk whose
offset is not the expected one is answered with the expected offset and
otherwise ignored. On the final chunk the follower: if it holds an entry at
`last_included_index` with term `last_included_term`, keeps the suffix after
it and drops the prefix; otherwise discards its whole log; sets `base_index`
and `base_term` to the boundary; replaces its state machine with the
snapshot state; sets `commit_index = last_applied = last_included_index`;
saves and syncs the record and the log; and only then replies with
`done = True`. The leader then sets `match_index[p] = last_included_index`
and `next_index[p] = last_included_index + 1`.

6.6 **Crash mid-transfer.** A follower that restarts loses its partial
buffer and answers the next chunk with `offset = 0`; the leader restarts the
transfer from the follower's offset. A leader that restarts is no longer
leader; a new leader starts its own transfer if the follower still needs
one. A node that restarts with a snapshot loads the state machine from it
and replays only the suffix.

6.7 **Traces.** A snapshot taken is traced as `snapshot` with
`last_included_index`, `last_included_term`, `dropped`. An install completed
is traced as `snapshot_installed` with the boundary. Both are committed-
visible and join `DIGEST_KINDS` (8.4) when the feature lands; that is a
documented digest-breaking change and follows the runbook.

## 7. Membership change — declared, not implemented

The seed runs with a fixed configuration. `JointConfiguration`,
`MembershipChange` and `configuration_from_entry_payload` in
`src/tidewater/membership.py` raise `FeatureNotImplemented`. The following is
the acceptance contract.

7.1 **Configuration entries.** A change is carried by log entries of kind
`config`. A **joint** entry's payload is `{"config": "joint", "old": [...],
"new": [...]}`; a **final** entry's payload is `{"config": "final", "new":
[...]}`. A node's configuration in force is given by the *latest* config
entry in its log, committed or not; it is re-derived on every append,
truncation and restart.

7.2 **Joint majorities.** While a node's latest config entry is joint, every
majority decision — votes counted by a candidate, acknowledgements counted
by the leader for 4.1 — requires a majority of `old` **and** a majority of
`new`, computed separately from the same set of acknowledgements.

7.3 **Catch-up.** Before proposing the joint entry the leader replicates to
the servers in `new - old` as non-voting learners until each one's
`match_index` is within `max_entries_per_append` of the leader's
`last_index`. Learners receive `AppendEntries` and reply to them but are not
counted in any majority and do not vote.

7.4 **Sequence.** The leader appends the joint entry; once it is committed
(under 7.2) the leader appends the final entry; once the final entry is
committed the change is complete. Only one change may be in flight at a
time; a second request is refused until the first completes.

7.5 **Leader not in the new configuration.** A leader that is not in `new`
continues to lead through the joint phase and steps down **immediately
after** committing the final entry, not before. It does not count itself
in the `new` majority while in the joint phase.

7.6 **Removed servers.** A server that is not in the configuration in force
still answers `RequestVote` and `AppendEntries` from members, but members
ignore its votes and acknowledgements. A removed server that times out and
sends pre-votes is denied by the lease rule (2.7) as long as the leader is
alive.

7.7 **Invariant.** At every tick, for any two live nodes with different
configurations in force, the two configurations must not admit disjoint
majorities (`membership_split`, 10.6).

## 8. Traces and digests

8.1 A trace is an append-only sequence of events. An event is
`(seq, tick, node, kind, fields)`; `seq` is its position, `node` is empty
for network and cluster events, and `fields` is a flat map of strings,
integers, booleans and lists. Events are recorded at the moment the thing
they describe happens, in the phase order of 1.2.

8.2 **Renderings.** Text: one line per event,
`SSSSSSS t=TTTTTT NODE   KIND   k=v ...`, fields sorted by key. JSONL: one
object per line, keys sorted, no whitespace. Both are pure functions of the
events.

8.3 **Event kinds** recorded by the seed. Node: `start`, `timeout`,
`prevote_start`, `election_start`, `vote`, `prevote`, `leader`, `step_down`,
`append`, `truncate`, `reject_append`, `commit`, `apply`, `propose`, `crash`,
`restart`, `skew`. Network: `send`, `deliver`, `drop`, `dup`, `partition`,
`heal`, `block`, `unblock`, `network`. Cluster: `schedule`,
`propose_pending`, `propose_rejected`, `violation`, `end`. A trace reader
must not fail on an unknown kind.

8.4 **Digest.** `Trace.digest()` is SHA-256 over the canonical JSON
(`tick`, `node`, `kind`, sorted `fields`; **not** `seq`) of the events whose
kind is in `DIGEST_KINDS = ("commit", "apply", "snapshot", "snapshot_installed", "violation")`, each followed
by a newline, in trace order. Message-level events do not take part. Two
runs with the same digest committed and applied the same entries on the
same nodes at the same ticks. A schedule's reference digest is stored in
`traces/<name>.digest` with the schedule's own digest, seed, tick count and
event counts.

8.5 **Divergence.** `first_divergence(reference, actual)` compares the two
digest-event sequences position by position and reports the first pair that
differs (or the first missing event). `tools/replay_trace.py` prints it.

## 9. Schedules

9.1 A schedule is a JSON object with `schema` (1), `name`, `description`,
`nodes` (sorted list), `seed`, `ticks`, `give_up_after`, `options` (node
options), `network` (network options) and `actions`. Node options:
`election_timeout` (>= 3), `heartbeat_interval` (>= 1, times three at most
`election_timeout`), `pre_vote`, `max_entries_per_append` (>= 1),
`compaction_threshold` (>= 0; 0 disables), `sync_policy`. Network options:
`min_delay` (>= 1), `max_delay` (>= `min_delay`, with `2 * max_delay <
election_timeout`), `drop_rate` and `dup_rate` in `[0, 1)`,
`dup_extra_delay` (>= 0).

9.2 **Actions** have `at` (in `[0, ticks)`) and `kind`. Kinds: `propose`
(`command`), `workload` (`count`, `every`, `key_prefix`, optional `op`,
`keys`, `client`), `partition` (`groups`), `heal`, `isolate` (`node`),
`block`/`unblock` (`src`, `dst`, optional `both`), `crash`/`restart`
(`node`), `skew` (`node`, `rate` and/or `offset`), `network` (any network
option). A `workload` expands to `count` proposes at `at + i * every`, with
key `key_prefix + (i mod keys)` (or `key_prefix + i` when `keys` is 0) and
value `v<at>.<i>`. Actions at one tick fire in file order; expanded
proposes keep their position by tick.

9.3 **Proposals.** A `propose` joins a pending queue; at every tick each
pending proposal is offered to the live leader of the highest term and
removed when accepted. The first failed offer is traced as
`propose_pending`. If `give_up_after > 0` a proposal older than that many
ticks is dropped and traced as `propose_rejected`.

9.4 **The corpus.** `schedules/*.json` is generated by
`tools/gen_schedules.py` from one root seed; `schedules/MANIFEST` holds the
SHA-256 of each file. `tools/gen_schedules.py --check` fails if a file
differs from what the generator produces or from its MANIFEST line.
`traces/<name>.digest` is produced by `tools/reference_traces.py`;
`--check` fails on any digest change. The procedure for changing either is
`docs/runbooks/regenerate-traces.md`.

## 10. Safety invariants

Checked after phase 5 of every tick over the live nodes by
`tidewater.invariants.InvariantMonitor`. A failure raises
`SafetyViolation(kind, detail, tick)` with `kind` from the closed set below,
is traced as `violation`, and ends the run.

10.1 `election_safety` — no two different nodes are leader in the same
term, ever.

10.2 `log_matching` — if two logs hold the same term at some index, they
hold identical entries at every index below it.

10.3 `leader_completeness` — a leader's log holds, with the same term, every
entry that was committed in an earlier term (indexes below its first
retained index excepted).

10.4 `state_machine_safety` — no two nodes apply different entries at the
same index, and no node applies at an index an entry different from the one
recorded as committed there. A second commit at an index with a different
entry is reported under this kind.

10.5 `commit_regression` — a node's commit index does not decrease between
ticks unless the node restarted in between.

10.6 `membership_split` — no two live nodes hold configurations that admit
two disjoint majorities.
