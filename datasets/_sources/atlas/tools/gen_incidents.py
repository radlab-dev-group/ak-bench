#!/usr/bin/env python3
"""Generate the incident-note corpus under ``docs/incidents``.

The corpus is deliberately large and mostly dull: a real store's incident
folder is 90 % "someone set the wrong profile" and the useful note is one
paragraph out of two hundred files. Finding the paragraph is a retrieval
problem, not a reading problem, which is why the notes are written in prose
about symptoms rather than in the vocabulary of the modules they explain.

Seven notes carry a rule that is not spelled out anywhere else in the words
the code uses; three of them describe a fix that was tried and reverted, and
saying so is the point. Regenerating is safe and produces byte-identical
output: the seed is fixed, the ordering is sorted, and no timestamp of "now"
is used.
"""

from __future__ import annotations

import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "incidents"

SYMPTOMS = [
    "a key read back stale after a node was drained",
    "an ack that no replica could corroborate",
    "a compaction that ran twice as long as expected",
    "a counter that advanced by two for one request",
    "a delete that came back after a restart",
    "a read that needed three replicas and got two",
    "a plan fingerprint that changed without an operator acting",
    "a shard that reported more keys than the cluster held",
    "a migration that restarted from zero every hour",
    "a profile that quietly overrode an environment variable",
    "a checksum error on a file nobody had touched",
    "a lease nobody could release",
    "an epoch that moved twice in one change",
    "a write that succeeded against a shard nobody owns",
    "a snapshot directory that filled the volume",
    "a tombstone that outlived the grace window by a week",
    "a rebalance that left one replica empty",
    "a transaction that aborted with no writer in the audit",
    "an audit line for a write the client never sent",
    "a digest that matched while the values did not",
]

CAUSES = [
    "an operator set the profile after the environment, expecting it to win",
    "a runbook step was performed in the wrong order",
    "a cache entry outlived the version it was read at",
    "a deprecated shim was wired into a new code path",
    "a generated file was edited by hand",
    "a grace window was measured from the sweep instead of the write",
    "a checkpoint named the wrong source replica",
    "a quorum was computed from the replica list instead of the configuration",
    "a marker frame was replayed as though it were a write",
    "a metric was read as a health signal and was not one",
    "a default was treated as a decision",
    "two clusters were pointed at one data directory",
    "a monitoring poll reopened the store and the poll won the race",
    "a v1 client computed placement for a v3 server",
    "a rollback took the binary but not the schema",
]

ACTIONS = [
    "the runbook now names the order of the steps",
    "the shim now logs a warning when it is reached",
    "the configuration is validated at startup instead of at first use",
    "the sweep measures from the write, not from the sweep",
    "the generated file is now checked against its source in review",
    "the metric was renamed so it cannot be read as health",
    "the checkpoint is deleted when the phase reaches done",
    "the client was pinned to the server's placement answer",
    "the audit now records the refusal as well as the write",
    "the directory layout moved to one cluster per volume",
    "the default was removed and the key made required",
    "the window was expressed in the same clock as the write",
    "the poll now asks the API instead of opening the store",
    "the docstring that misled the author was rewritten the same day",
]


def noise(index: int, rng: random.Random) -> str:
    number = f"INC-{1000 + index}"
    symptom = rng.choice(SYMPTOMS)
    cause = rng.choice(CAUSES)
    action = rng.choice(ACTIONS)
    module = rng.choice(
        ["placement", "config", "audit", "cache", "retention", "migration", "antientropy", "cli"]
    )
    severity = rng.choice(["low", "low", "medium", "high"])
    tags = rng.sample(["ops", "config", "drain", "profile", "quorum", "cache", "grace", "epoch"], k=3)
    return f"""---
id: {number}
severity: {severity}
module: {module}
tags: {", ".join(tags)}
---

# {number}: {symptom}

## What we saw

{symptom.capitalize()} on one shard of a three-replica cluster during a
routine change. Nothing in the repository suite reproduced it, and the suite
was green throughout, which at the time felt reassuring and was not.

## What it turned out to be

{cause.capitalize()}. The fix was small; the reason it took a day was that
the symptom named a different subsystem from the one at fault, and the dash
for the module nobody suspected was the only one with useful numbers.

## What we changed

{action.capitalize()}. No store behaviour changed for a correctly configured
cluster, and that is the whole reason this note is in the archive rather than
in a postmortem template.

## Read next

Nothing in particular. This one is in the archive because we want it found and
ruled out quickly the next time.
"""


DECISIVE = [
    (
        "the-authoritative-copy-was-the-one-nobody-published",
        "recovery",
        """The replica came back with two snapshot files in its directory and adopted
the newer one. It should not have. Adoption is not recovery: what recovery
does is read the pointer file and ask for the image it names, and the pointer
is the record of the decision the process made before it died. A file sitting
in the same directory is not a decision, it is a file — it may have been
written by a run that crashed between writing and committing, and a recovery
that reads it is inventing a publication the cluster never agreed to. The
older image, named by the pointer, is the state of the world. Everything else
in that directory is debris, including the debris that looks newer.""",
    ),
    (
        "the-window-opens-after-the-number-not-at-it",
        "recovery",
        """The replay started one record too early and nobody noticed for a fortnight,
because the record it replayed was one that had already been folded into the
image. The number in the header of an image is the number of the last thing it
*contains*, and a window that starts at that number replays it a second time.
For a row holding a count that is not harmless: the second application is
arithmetically valid, checksum-clean, and wrong. Ask for what came after the
number, always, and if a deployment ever says otherwise, say it in exactly one
place so there is one place to look.""",
    ),
    (
        "the-cut-that-ate-a-committed-week",
        "durability",
        """A tail was torn, and the repair cut back to the last place a transaction had
started. That is a cut, and it is the wrong one. Everything before the damage
had already been promised to a caller — a commit had been written for it, and
a promise made by a durable commit is not undone by damage further along the
file. The repair goes to the end of the last thing that could be read, and
stops. The damaged remainder goes; the promised remainder stays. A repair that
eats a committed transaction is a data-loss bug wearing the clothes of a
recovery feature, and the test for it is to write two transactions, tear the
second, and insist the first is still there.""",
    ),
    (
        "the-token-that-matched-by-accident",
        "fencing",
        """A drained worker acked work it had not finished, because the comparison let a
number through that was merely not-behind. Tokens are not progress bars. The
number a caller holds either is the one the store is holding at this moment or
it is not, and anything else means the caller has seen something the store has
not, which is the same category of wrong as being behind. Being behind is the
drained worker; being ahead is the one that has already been replaced and is
still talking. Refuse both, and refuse the epoch before you refuse the number,
because a caller from an epoch that has ended is not late, it is gone.""",
    ),
    (
        "two-halves-of-one-decision",
        "placement",
        """Which partition a key lives in, and which machine is allowed to answer for
it, are different questions, and this cluster asks them of different places.
The first depends on the key and nothing else. The second depends on the plan
of the moment, and a plan is a snapshot of a decision that has since been
remade. The incident was a rebalance where a caller asked the second question
of a plan it had carried across the switch, and the answer was a machine that
no longer held the key. Nothing raised. A write went somewhere, and later a
read did not find it.""",
    ),
    (
        "the-move-that-published-first",
        "rebalance",
        """Five steps, and the order is the whole feature: build, work out what moves,
copy it and bring the destination up to date, announce, then let go. The
cluster we debugged announced before it copied, which is a period in which a
write lands on a machine with no key, and then let go before it copied, which
is a key that is simply not there. Both faults pass every single-write test
in existence, because a single write does not straddle an announcement. The
audit trail is the report the run leaves behind; if it shows an announcement
before a copy finished, the run is wrong and no amount of green afterwards
saves it.""",
    ),
    (
        "the-winner-is-the-name-not-the-hour",
        "convergence",
        """Two writers, neither seeing the other, one row. The tie is not broken by
timestamp, and it is not broken by who wrote last in wall-clock order, and it
is not broken by which replica noticed first. It is broken by the name of the
writer, and the greatest name wins, and every replica must reach that same
answer or repair makes the disagreement permanent instead of curing it. We
changed the direction of this comparison once, on a branch, in one module, and
the cluster spent a week in a state where two replicas each confidently
repaired the other back to its own version. Whichever direction it is, it is
one direction, in one place.""",
    ),
]

REVERTED = [
    (
        "the-inclusive-window-that-looked-fine",
        "recovery",
        """We made the replay window inclusive of the image's own number, and for three
weeks it looked like an improvement: fewer records were skipped on open, and
the open got faster. It was wrong on the first counter that was incremented
twice. The inclusive form is not "more conservative" — it re-applies work that
has been done. This note is here because the change is tempting and because
the reverted commit is still in the history, and whoever finds it should read
the note titled *the window opens after the number, not at it* before
reproducing it.""",
    ),
    (
        "adopting-the-newest-image",
        "recovery",
        """A one-line operational convenience: when the pointer is missing, take the
newest image. It gets you out of an incident on a Tuesday and it publishes a
write the cluster never agreed to on the Tuesday after. It was reverted. If
the pointer is gone, the answer is to restore the pointer deliberately, by
hand, with the operator saying which image is the state of the world — not to
let a recovery routine guess.""",
    ),
    (
        "permissive-everywhere",
        "fencing",
        """`generation_check = permissive` exists for one migration in which a peer is
behind. Someone set it cluster-wide to stop an alert, and the alert stopped
because the writes it was reporting were now accepted. A permissive check is
a narrower door, not an open one: a caller ahead of the store is refused even
in permissive mode, and a caller from a finished epoch is refused in every
mode. The setting that stops the noise is usually the one that names the peer
that is behind, not the one that stops asking.""",
    ),
]


def decisive_body(index: int, entry, *, reverted: bool) -> str:
    slug, module, text = entry
    number = f"INC-{2900 + index}"
    kind = "a fix we reverted" if reverted else "the rule behind a rule"
    return f"""---
id: {number}
severity: high
module: {module}
kind: {kind}
tags: protocol, read-first
---

# {number}: {slug.replace('-', ' ')}

{text}
"""


def main() -> int:
    rng = random.Random(20261108)
    OUT.mkdir(parents=True, exist_ok=True)
    for existing in OUT.glob("*.md"):
        existing.unlink()
    written = 0
    for index in range(160):
        path = OUT / f"INC-{1000 + index:04d}.md"
        path.write_text(noise(index, rng), encoding="utf-8")
        written += 1
    for index, entry in enumerate(DECISIVE):
        path = OUT / f"INC-{2900 + index:04d}-{entry[0]}.md"
        path.write_text(decisive_body(index, entry, reverted=False), encoding="utf-8")
        written += 1
    for index, entry in enumerate(REVERTED):
        path = OUT / f"INC-{2950 + index:04d}-{entry[0]}.md"
        path.write_text(decisive_body(index, entry, reverted=True), encoding="utf-8")
        written += 1
    print(f"wrote {written} incident notes to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
