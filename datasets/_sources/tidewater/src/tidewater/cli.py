"""The operator driver: ``python -m tidewater``.

::

    python -m tidewater run schedules/baseline.json --seed 7 --ticks 3000 --trace out.jsonl
    python -m tidewater run schedules/baseline.json --text            # stream the trace
    python -m tidewater describe schedules/partition-heal.json
    python -m tidewater digest out.jsonl

``run`` prints a summary (digest, leaders by term, commit indexes, network
counters) and exits 0 when no safety violation occurred, 2 when one did. The
trace is written even on a violation, so the ``violation`` event is the last
line and the tick it carries is where to start reading.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Sequence

from .cluster import Cluster
from .errors import TidewaterError
from .schedule import Schedule, load_schedule
from .trace import Trace


def _with_overrides(schedule: Schedule, seed: int | None, ticks: int | None) -> Schedule:
    if ticks is None:
        return schedule
    kept = [a for a in schedule.expanded_actions() if a.at < ticks]
    return Schedule(
        name=schedule.name, description=schedule.description, nodes=schedule.nodes,
        seed=schedule.seed if seed is None else seed, ticks=ticks, actions=kept,
        node_options=schedule.node_options, network_options=schedule.network_options,
        give_up_after=schedule.give_up_after,
    )


def cmd_run(args: argparse.Namespace) -> int:
    schedule = _with_overrides(load_schedule(args.schedule), args.seed, args.ticks)
    trace = Trace()
    if args.text:
        trace.subscribe(lambda event: print(event.render()))
    cluster = Cluster(schedule, seed=args.seed, trace=trace)
    result = cluster.run()
    if args.trace:
        count = trace.write_jsonl(args.trace)
        print(f"trace      {args.trace} ({count} events)", file=sys.stderr if args.text else sys.stdout)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    elif not args.quiet:
        print(result.render())
        counts = trace.counts()
        print("kinds      " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0 if result.ok else 2


def cmd_describe(args: argparse.Namespace) -> int:
    schedule = load_schedule(args.schedule)
    print(schedule.summary())
    print(f"digest     {schedule.digest()}")
    print(f"options    " + ", ".join(f"{k}={v}" for k, v in schedule.node_options.to_dict().items()))
    print(f"network    " + ", ".join(f"{k}={v}" for k, v in schedule.network_options.to_dict().items()))
    if schedule.description:
        print(f"about      {schedule.description}")
    for action in (schedule.expanded_actions() if args.expand else schedule.actions):
        print("  " + action.summary())
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    trace = Trace.read_jsonl(args.trace)
    print(trace.digest())
    if args.verbose:
        print(f"events {len(trace)} digest-events {len(trace.digest_events())}")
        for k, v in trace.counts().items():
            print(f"  {k:<18} {v}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tidewater", description="Deterministic replicated-log simulator")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a schedule")
    run.add_argument("schedule", type=pathlib.Path)
    run.add_argument("--seed", type=int, default=None, help="override the schedule's seed")
    run.add_argument("--ticks", type=int, default=None, help="override the schedule's length")
    run.add_argument("--trace", type=pathlib.Path, default=None, help="write the JSONL trace here")
    run.add_argument("--text", action="store_true", help="stream the text trace to stdout as it happens")
    run.add_argument("--json", action="store_true", help="print the summary as JSON")
    run.add_argument("--quiet", action="store_true", help="print nothing but errors")
    run.set_defaults(func=cmd_run)

    describe = sub.add_parser("describe", help="print a schedule's actions")
    describe.add_argument("schedule", type=pathlib.Path)
    describe.add_argument("--expand", action="store_true", help="unroll workloads")
    describe.set_defaults(func=cmd_describe)

    digest = sub.add_parser("digest", help="digest of a JSONL trace")
    digest.add_argument("trace", type=pathlib.Path)
    digest.add_argument("--verbose", "-v", action="store_true")
    digest.set_defaults(func=cmd_digest)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except TidewaterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
