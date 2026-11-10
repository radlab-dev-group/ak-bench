#!/usr/bin/env python3
"""Re-run a schedule and compare it with a reference.

::

    python tools/replay_trace.py schedules/long-haul.json
    python tools/replay_trace.py schedules/long-haul.json --reference traces/long-haul.digest
    python tools/replay_trace.py schedules/long-haul.json --reference-trace /tmp/ref/long-haul.jsonl
    python tools/replay_trace.py schedules/long-haul.json --seed 5 --ticks 1500 --save /tmp/out.jsonl

Without a reference the tool looks for ``traces/<name>.digest`` next to the
corpus. With ``--reference-trace`` (a full JSONL trace) it prints the **first
divergent digest event** — the reference's and the actual one, with tick and
sequence numbers — which is the fastest way to find where a behaviour change
first shows. With only a digest it prints both digests and the last few
digest events of the new run.

``--all`` compares events of every kind, not only the digest kinds; use it
when a change was not supposed to alter anything at all, including message
timing.

Exit status: 0 when the run matches the reference, 1 when it does not, 2
when the reference is missing or unreadable.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tidewater.cluster import Cluster  # noqa: E402
from tidewater.errors import TidewaterError  # noqa: E402
from tidewater.schedule import Schedule, load_schedule  # noqa: E402
from tidewater.trace import Trace, first_divergence  # noqa: E402


def shortened(schedule: Schedule, ticks: int | None, seed: int | None) -> Schedule:
    if ticks is None and seed is None:
        return schedule
    new_ticks = schedule.ticks if ticks is None else ticks
    kept = [a for a in schedule.expanded_actions() if a.at < new_ticks]
    return Schedule(
        name=schedule.name, description=schedule.description, nodes=schedule.nodes,
        seed=schedule.seed if seed is None else seed, ticks=new_ticks, actions=kept,
        node_options=schedule.node_options, network_options=schedule.network_options,
        give_up_after=schedule.give_up_after,
    )


def read_digest_file(path: pathlib.Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition("  ")
        if key.strip() == "trace_digest":
            return value.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("schedule", type=pathlib.Path)
    parser.add_argument("--reference", type=pathlib.Path, default=None, help="a .digest file")
    parser.add_argument("--reference-trace", type=pathlib.Path, default=None, help="a full .jsonl trace")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--ticks", type=int, default=None)
    parser.add_argument("--save", type=pathlib.Path, default=None, help="write the new JSONL trace here")
    parser.add_argument("--all", action="store_true", help="compare every event kind, not only digest kinds")
    parser.add_argument("--tail", type=int, default=5, help="digest events to print on mismatch")
    args = parser.parse_args(argv)

    try:
        schedule = shortened(load_schedule(args.schedule), args.ticks, args.seed)
    except TidewaterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    cluster = Cluster(schedule)
    result = cluster.run()
    if args.save:
        cluster.trace.write_jsonl(args.save)
    print(f"schedule     {schedule.name} seed={schedule.seed} ticks={result.ticks}")
    print(f"events       {result.events} (digest events {len(cluster.trace.digest_events())})")
    print(f"trace_digest {result.digest}")
    if result.violation is not None:
        print(f"VIOLATION    {result.violation}")

    if args.reference_trace is not None:
        try:
            reference = Trace.read_jsonl(args.reference_trace)
        except TidewaterError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        divergence = first_divergence(reference, cluster.trace, digest_only=not args.all)
        if divergence is None:
            print(f"match        {args.reference_trace} ({'all events' if args.all else 'digest events'})")
            return 0
        print(divergence.render())
        return 1

    reference_path = args.reference
    if reference_path is None:
        reference_path = ROOT / "traces" / f"{schedule.name}.digest"
    if not reference_path.exists():
        print(f"no reference at {reference_path}; nothing to compare", file=sys.stderr)
        return 2
    expected = read_digest_file(reference_path)
    if expected is None:
        print(f"{reference_path} has no trace_digest line", file=sys.stderr)
        return 2
    if expected == result.digest:
        print(f"match        {reference_path}")
        return 0
    print(f"MISMATCH     reference {expected}")
    print(f"             actual    {result.digest}")
    tail = cluster.trace.digest_events()[-args.tail:]
    if tail:
        print(f"last {len(tail)} digest events of this run:")
        for event in tail:
            print("  " + event.render())
    return 1


if __name__ == "__main__":
    sys.exit(main())
