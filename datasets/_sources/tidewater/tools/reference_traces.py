#!/usr/bin/env python3
"""Regenerate (or check) the reference trace digests for the schedule corpus.

::

    python tools/reference_traces.py                 # write traces/<name>.digest for every schedule
    python tools/reference_traces.py --check         # exit 1 if any digest differs
    python tools/reference_traces.py --only long-haul --check
    python tools/reference_traces.py --write-traces /tmp/ref   # also keep full JSONL traces

A ``.digest`` file is a small key/value text document::

    schedule        long-haul
    schedule_digest 3f1c...            # Schedule.digest(): the input
    seed            481927
    ticks           6000
    events          15834              # total trace events
    digest_events   1920               # events that take part in the digest
    trace_digest    9a0e...            # Trace.digest(): the output

``--check`` recomputes every schedule's trace and compares ``trace_digest``
(and ``schedule_digest``, so a changed schedule is reported as "input
changed" rather than as a mysterious output change). The first mismatching
schedule is printed with both digests and the position of the first
divergent digest event when a full reference trace is available next to the
digest (``traces/<name>.jsonl``); otherwise the tail of the recomputed
digest events is shown so the reader has tick numbers to start from.

The procedure that decides *when* to run this without ``--check`` is in
``docs/runbooks/regenerate-traces.md``. Short version: only after
``tools/gen_schedules.py --check`` passes, and only when the change you made
was meant to alter what gets committed where and when.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tidewater.cluster import Cluster  # noqa: E402
from tidewater.schedule import Schedule, load_corpus  # noqa: E402
from tidewater.trace import Trace, first_divergence  # noqa: E402

DIGEST_SUFFIX = ".digest"


def run(schedule: Schedule) -> tuple[Cluster, dict[str, str]]:
    cluster = Cluster(schedule)
    result = cluster.run()
    record = {
        "schedule": schedule.name,
        "schedule_digest": schedule.digest(),
        "seed": str(schedule.seed),
        "ticks": str(result.ticks),
        "events": str(result.events),
        "digest_events": str(len(cluster.trace.digest_events())),
        "trace_digest": result.digest,
    }
    if result.violation is not None:
        record["violation"] = f"{result.violation.kind}@{result.violation.tick}"
    return cluster, record


def render(record: dict[str, str]) -> str:
    width = max(len(k) for k in record)
    return "\n".join(f"{k:<{width}}  {v}" for k, v in record.items()) + "\n"


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("  ")
        out[key.strip()] = value.strip()
    return out


def write_all(schedules: list[Schedule], traces_dir: pathlib.Path, full_dir: pathlib.Path | None) -> int:
    traces_dir.mkdir(parents=True, exist_ok=True)
    for schedule in schedules:
        cluster, record = run(schedule)
        path = traces_dir / f"{schedule.name}{DIGEST_SUFFIX}"
        path.write_text(render(record), encoding="utf-8")
        note = f" VIOLATION {record['violation']}" if "violation" in record else ""
        print(f"wrote {path.name}: {record['trace_digest'][:16]} ({record['events']} events){note}")
        if full_dir is not None:
            full_dir.mkdir(parents=True, exist_ok=True)
            cluster.trace.write_jsonl(full_dir / f"{schedule.name}.jsonl")
    return 0


def check_all(schedules: list[Schedule], traces_dir: pathlib.Path, verbose: bool) -> int:
    failures = 0
    for schedule in schedules:
        path = traces_dir / f"{schedule.name}{DIGEST_SUFFIX}"
        if not path.exists():
            print(f"MISSING  {schedule.name}: no {path.name}; run tools/reference_traces.py")
            failures += 1
            continue
        recorded = parse(path.read_text(encoding="utf-8"))
        cluster, actual = run(schedule)
        if recorded.get("schedule_digest") != actual["schedule_digest"]:
            print(f"INPUT    {schedule.name}: schedule digest changed "
                  f"{recorded.get('schedule_digest', '?')[:16]} -> {actual['schedule_digest'][:16]} "
                  f"(regenerate schedules first: tools/gen_schedules.py --lock)")
            failures += 1
            continue
        if recorded.get("trace_digest") == actual["trace_digest"]:
            if verbose:
                print(f"ok       {schedule.name}: {actual['trace_digest'][:16]} ({actual['events']} events)")
            continue
        failures += 1
        print(f"MISMATCH {schedule.name}: reference {recorded.get('trace_digest', '?')[:16]} "
              f"actual {actual['trace_digest'][:16]} "
              f"(events {recorded.get('events', '?')} -> {actual['events']}, "
              f"digest events {recorded.get('digest_events', '?')} -> {actual['digest_events']})")
        full = traces_dir / f"{schedule.name}.jsonl"
        if full.exists():
            divergence = first_divergence(Trace.read_jsonl(full), cluster.trace)
            if divergence is not None:
                print("  " + divergence.render().replace("\n", "\n  "))
        else:
            tail = cluster.trace.digest_events()[-5:]
            print("  last digest events of the recomputed trace:")
            for event in tail:
                print("    " + event.render())
        if "violation" in actual:
            print(f"  recomputed run ended with a safety violation: {actual['violation']}")
    if failures:
        print(f"reference trace check FAILED: {failures} of {len(schedules)} schedules differ")
        return 1
    print(f"reference trace check OK: {len(schedules)} schedules match traces/")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schedules", type=pathlib.Path, default=ROOT / "schedules")
    parser.add_argument("--traces", type=pathlib.Path, default=ROOT / "traces")
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    parser.add_argument("--only", action="append", default=[], help="restrict to these schedule names")
    parser.add_argument("--write-traces", type=pathlib.Path, default=None,
                        help="also write full JSONL traces into this directory (not --check)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    schedules = load_corpus(args.schedules)
    if args.only:
        wanted = set(args.only)
        schedules = [s for s in schedules if s.name in wanted]
        missing = wanted - {s.name for s in schedules}
        if missing:
            parser.error(f"unknown schedule(s): {sorted(missing)}")
    if not schedules:
        parser.error(f"no schedules in {args.schedules}")
    if args.check:
        return check_all(schedules, args.traces, args.verbose)
    return write_all(schedules, args.traces, args.write_traces)


if __name__ == "__main__":
    sys.exit(main())
