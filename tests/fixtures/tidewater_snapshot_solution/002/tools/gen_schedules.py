#!/usr/bin/env python3
"""Regenerate the schedule corpus deterministically from one seed.

::

    python tools/gen_schedules.py                 # write schedules/*.json
    python tools/gen_schedules.py --lock          # ... and write schedules/MANIFEST
    python tools/gen_schedules.py --check         # exit 1 if disk differs from generator or MANIFEST
    python tools/gen_schedules.py --seed 99 --out /tmp/corpus --lock

The corpus is *generated*, not hand-written. Every schedule is a function of
the root seed and its name, so a reviewer can tell a deliberate corpus
change (the generator changed, the MANIFEST was re-locked, the reference
digests were regenerated — see ``docs/runbooks/regenerate-traces.md``) from
an accidental one (a file was edited in place and the MANIFEST no longer
matches). ``--check`` is what CI and the repository suite run; it compares
three things and reports the first that disagrees:

1. each generated schedule against the file on disk, byte for byte;
2. each file on disk against its line in ``MANIFEST``;
3. the set of files against the set of MANIFEST lines (extra or missing).

Exit status: 0 when everything agrees, 1 on any difference, 2 on a usage
error.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tidewater.network import NetworkOptions  # noqa: E402
from tidewater.node import NodeOptions  # noqa: E402
from tidewater.rng import SeedTree  # noqa: E402
from tidewater.schedule import Action, Schedule, file_digest, nodes_named  # noqa: E402

DEFAULT_SEED = 20261110
MANIFEST_NAME = "MANIFEST"

FIVE = nodes_named(5)
THREE = nodes_named(3)


def _a(at: int, kind: str, **args) -> Action:
    return Action(at=at, kind=kind, args=args)


def _workload(at: int, count: int, every: int, prefix: str, **extra) -> Action:
    return _a(at, "workload", count=count, every=every, key_prefix=prefix, **extra)


def _seed(tree: SeedTree, name: str) -> int:
    return tree.seed_for("schedule", name) % 1_000_000


# Each generator takes (tree) and returns a Schedule. Order here is the
# order of the corpus; names are the file names.


def baseline_steady(tree: SeedTree) -> Schedule:
    return Schedule(
        name="baseline-steady",
        description="Five nodes, no faults, a steady trickle of writes. The digest every other schedule is read against.",
        nodes=FIVE, seed=_seed(tree, "baseline-steady"), ticks=2000,
        actions=[_workload(10, 60, 25, "k")],
    )


def partition_minority(tree: SeedTree) -> Schedule:
    return Schedule(
        name="partition-minority",
        description="Two nodes cut off from three, three times with different pairs, so that whoever leads ends up in the minority at least once. The majority side keeps committing; the minority must not.",
        nodes=FIVE, seed=_seed(tree, "partition-minority"), ticks=3600,
        actions=[
            _workload(10, 20, 10, "a"),
            _a(400, "partition", groups=[["n1", "n2"], ["n3", "n4", "n5"]]),
            _workload(420, 20, 15, "b"),
            _a(1200, "heal"),
            _workload(1300, 10, 10, "c"),
            _a(1500, "partition", groups=[["n3", "n4"], ["n1", "n2", "n5"]]),
            _workload(1520, 20, 15, "d"),
            _a(2300, "heal"),
            _workload(2400, 10, 10, "e"),
            _a(2600, "partition", groups=[["n1", "n5"], ["n2", "n3", "n4"]]),
            _workload(2620, 20, 15, "f"),
            _a(3300, "heal"),
            _workload(3350, 10, 10, "g"),
        ],
    )


def leader_isolated(tree: SeedTree) -> Schedule:
    actions = [_workload(10, 12, 10, "k")]
    tick = 300
    for i, node in enumerate(FIVE):
        actions.append(_a(tick, "isolate", node=node))
        actions.append(_workload(tick + 2, 12, 5, f"p{i}"))
        actions.append(_a(tick + 400, "heal"))
        actions.append(_workload(tick + 420, 6, 5, f"q{i}"))
        tick += 560
    return Schedule(
        name="leader-isolated",
        description="Isolate every node in turn, so the leader of the moment is cut off at least once. Its uncommitted tail must be truncated after the heal, and nothing committed may go with it.",
        nodes=FIVE, seed=_seed(tree, "leader-isolated"), ticks=tick + 200,
        actions=actions,
    )


def partition_heal_storm(tree: SeedTree) -> Schedule:
    actions = [_workload(10, 10, 10, "w")]
    tick = 300
    splits = [
        [["n1", "n2"], ["n3", "n4", "n5"]],
        [["n1", "n2", "n3"], ["n4", "n5"]],
        [["n1"], ["n2", "n3"], ["n4", "n5"]],
        [["n1", "n5"], ["n2", "n3", "n4"]],
        [["n2"], ["n1", "n3", "n4", "n5"]],
        [["n3", "n4"], ["n1", "n2", "n5"]],
    ]
    for i, groups in enumerate(splits):
        actions.append(_a(tick, "partition", groups=groups))
        actions.append(_workload(tick + 5, 8, 10, f"s{i}"))
        actions.append(_a(tick + 260, "heal"))
        actions.append(_workload(tick + 300, 4, 10, f"h{i}"))
        tick += 420
    return Schedule(
        name="partition-heal-storm",
        description="Six partitions in a row, each healed before the next. Pre-vote keeps the term count low; without it this is an election storm.",
        nodes=FIVE, seed=_seed(tree, "partition-heal-storm"), ticks=tick + 200,
        actions=actions,
    )


def crash_restart_follower(tree: SeedTree) -> Schedule:
    return Schedule(
        name="crash-restart-follower",
        description="n2 crashes, misses writes, restarts and must catch up without losing anything it had acknowledged.",
        nodes=FIVE, seed=_seed(tree, "crash-restart-follower"), ticks=2200,
        actions=[
            _workload(10, 10, 10, "a"),
            _a(300, "crash", node="n2"),
            _workload(320, 20, 10, "b"),
            _a(900, "restart", node="n2"),
            _workload(1000, 10, 10, "c"),
            _a(1500, "crash", node="n2"),
            _a(1560, "restart", node="n2"),
            _workload(1600, 10, 10, "d"),
        ],
    )


def crash_leader_chain(tree: SeedTree) -> Schedule:
    return Schedule(
        name="crash-leader-chain",
        description="Nodes crash one after another, never more than two down at once. Each new leader must hold every committed entry.",
        nodes=FIVE, seed=_seed(tree, "crash-leader-chain"), ticks=3600,
        actions=[
            _workload(10, 10, 10, "a"),
            _a(300, "crash", node="n4"),
            _workload(320, 10, 10, "b"),
            _a(800, "crash", node="n1"),
            _workload(820, 10, 10, "c"),
            _a(1300, "restart", node="n4"),
            _a(1400, "crash", node="n3"),
            _workload(1420, 10, 10, "d"),
            _a(1900, "restart", node="n1"),
            _a(2000, "crash", node="n5"),
            _workload(2020, 10, 10, "e"),
            _a(2500, "restart", node="n3"),
            _a(2600, "restart", node="n5"),
            _workload(2700, 20, 10, "f"),
        ],
    )


def lossy_network(tree: SeedTree) -> Schedule:
    return Schedule(
        name="lossy-network",
        description="Fifteen percent drops, ten percent duplicates, wide delay. Duplicated and reordered appends must be idempotent.",
        nodes=FIVE, seed=_seed(tree, "lossy-network"), ticks=3000,
        network_options=NetworkOptions(min_delay=1, max_delay=6, drop_rate=0.15, dup_rate=0.10, dup_extra_delay=6),
        actions=[
            _workload(10, 80, 20, "k"),
            _a(1800, "network", drop_rate=0.30, dup_rate=0.20),
            _workload(1810, 40, 15, "m"),
        ],
    )


def clock_skew(tree: SeedTree) -> Schedule:
    return Schedule(
        name="clock-skew",
        description="n2 runs three times fast, n5 four times fast from mid-run. Fast clocks time out early; pre-vote should stop them from stealing leadership.",
        nodes=FIVE, seed=_seed(tree, "clock-skew"), ticks=2600,
        actions=[
            _workload(10, 15, 10, "a"),
            _a(200, "skew", node="n2", rate=3),
            _workload(220, 20, 10, "b"),
            _a(1200, "skew", node="n5", rate=4),
            _workload(1220, 20, 10, "c"),
            _a(2000, "skew", node="n2", rate=1),
            _a(2000, "skew", node="n5", rate=1),
            _workload(2050, 10, 10, "d"),
        ],
    )


def three_node_minority_crash(tree: SeedTree) -> Schedule:
    return Schedule(
        name="three-node-minority-crash",
        description="A three-node cluster loses one node, then a different one, with writes in between. Two of three is a majority, one is not.",
        nodes=THREE, seed=_seed(tree, "three-node-minority-crash"), ticks=2400,
        actions=[
            _workload(10, 10, 10, "a"),
            _a(300, "crash", node="n3"),
            _workload(320, 15, 10, "b"),
            _a(900, "restart", node="n3"),
            _a(1000, "crash", node="n1"),
            _workload(1020, 15, 10, "c"),
            _a(1700, "restart", node="n1"),
            _workload(1800, 10, 10, "d"),
        ],
    )


def flapping_links(tree: SeedTree) -> Schedule:
    actions = [_workload(10, 10, 10, "a")]
    tick = 300
    pairs = [("n1", "n3"), ("n2", "n4"), ("n3", "n5"), ("n1", "n5"), ("n2", "n3"), ("n4", "n5")]
    for i, (src, dst) in enumerate(pairs):
        actions.append(_a(tick, "block", src=src, dst=dst))
        actions.append(_workload(tick + 10, 6, 10, f"f{i}"))
        actions.append(_a(tick + 150, "unblock", src=src, dst=dst))
        tick += 220
    return Schedule(
        name="flapping-links",
        description="Single links fail and recover in sequence. No partition ever separates a majority, so the leader should keep committing throughout.",
        nodes=FIVE, seed=_seed(tree, "flapping-links"), ticks=tick + 200,
        actions=actions,
    )


def asymmetric_link(tree: SeedTree) -> Schedule:
    return Schedule(
        name="asymmetric-link",
        description="One-way link failures: n3 can hear n1 but n1 cannot hear n3, then the reverse. Heartbeats arrive, acks do not.",
        nodes=FIVE, seed=_seed(tree, "asymmetric-link"), ticks=3000,
        actions=[
            _workload(10, 10, 10, "a"),
            _a(300, "block", src="n3", dst="n1", both=False),
            _workload(320, 20, 10, "b"),
            _a(1000, "unblock", src="n3", dst="n1", both=False),
            _a(1100, "block", src="n1", dst="n3", both=False),
            _workload(1120, 20, 10, "c"),
            _a(1900, "unblock", src="n1", dst="n3", both=False),
            _a(2000, "block", src="n4", dst="n2", both=False),
            _a(2000, "block", src="n5", dst="n2", both=False),
            _workload(2020, 20, 10, "d"),
            _a(2700, "heal"),
        ],
    )


def compaction_quiet(tree: SeedTree) -> Schedule:
    return Schedule(
        name="compaction-quiet",
        description="Compaction on, no faults: every node snapshots its own state at its own pace while the cluster writes. The digest is the value the snapshot feature must keep stable.",
        nodes=FIVE, seed=_seed(tree, "compaction-quiet"), ticks=2400,
        node_options=NodeOptions(compaction_threshold=24),
        actions=[_workload(10, 80, 20, "k")],
    )


def compaction_catchup(tree: SeedTree) -> Schedule:
    return Schedule(
        name="compaction-catchup",
        description="Compaction on, and n2 is cut off long enough that the cluster compacts away the entries it needs. When the link heals the leader can no longer replay n2 forward: it has to bring it level with a snapshot, chunk by chunk, and keep the cluster committing while it does.",
        nodes=FIVE, seed=_seed(tree, "compaction-catchup"), ticks=3200,
        node_options=NodeOptions(compaction_threshold=20),
        network_options=NetworkOptions(min_delay=1, max_delay=4, drop_rate=0.04, dup_rate=0.02),
        actions=[
            _workload(10, 20, 15, "a"),
            _a(300, "isolate", node="n2"),
            _workload(320, 70, 15, "b"),
            _a(1900, "heal"),
            _workload(1950, 40, 15, "c"),
        ],
    )


def long_haul(tree: SeedTree) -> Schedule:
    return Schedule(
        name="long-haul",
        description="Everything at once over six thousand ticks: partitions, crashes, skew, loss. The trace runs to many thousands of events.",
        nodes=FIVE, seed=_seed(tree, "long-haul"), ticks=6000,
        network_options=NetworkOptions(min_delay=1, max_delay=4, drop_rate=0.05, dup_rate=0.03),
        actions=[
            _workload(10, 40, 10, "a"),
            _a(500, "partition", groups=[["n1", "n2"], ["n3", "n4", "n5"]]),
            _workload(510, 20, 10, "b"),
            _a(1000, "heal"),
            _a(1200, "crash", node="n3"),
            _workload(1210, 20, 10, "c"),
            _a(1700, "restart", node="n3"),
            _a(1900, "skew", node="n1", rate=3),
            _workload(1910, 20, 10, "d"),
            _a(2500, "isolate", node="n5"),
            _workload(2510, 20, 10, "e"),
            _a(3000, "heal"),
            _a(3100, "network", drop_rate=0.20, dup_rate=0.10),
            _workload(3110, 40, 10, "f"),
            _a(3700, "network", drop_rate=0.05, dup_rate=0.03),
            _a(3800, "crash", node="n1"),
            _a(3801, "crash", node="n2"),
            _workload(3810, 20, 10, "g"),
            _a(4300, "restart", node="n1"),
            _a(4300, "restart", node="n2"),
            _a(4400, "partition", groups=[["n1", "n2", "n3"], ["n4", "n5"]]),
            _workload(4410, 20, 10, "h"),
            _a(4900, "heal"),
            _a(5000, "skew", node="n1", rate=1),
            _workload(5010, 60, 10, "i"),
        ],
    )


GENERATORS = [
    baseline_steady,
    partition_minority,
    leader_isolated,
    partition_heal_storm,
    crash_restart_follower,
    crash_leader_chain,
    lossy_network,
    clock_skew,
    three_node_minority_crash,
    flapping_links,
    asymmetric_link,
    long_haul,
    compaction_quiet,
    compaction_catchup,
]


def generate(seed: int) -> list[Schedule]:
    tree = SeedTree(seed)
    schedules = [gen(tree) for gen in GENERATORS]
    for schedule in schedules:
        schedule.validate()
    names = [s.name for s in schedules]
    if len(set(names)) != len(names):
        raise SystemExit("generator produced duplicate schedule names")
    return schedules


def manifest_lines(directory: pathlib.Path) -> list[str]:
    return [f"{file_digest(path)}  {path.name}" for path in sorted(directory.glob("*.json"))]


def read_manifest(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        out[name.strip()] = digest.strip()
    return out


def write(schedules: list[Schedule], out: pathlib.Path, lock: bool) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for schedule in schedules:
        (out / f"{schedule.name}.json").write_text(schedule.to_json(), encoding="utf-8")
        print(f"wrote {out / (schedule.name + '.json')}")
    if lock:
        lines = ["# sha256 of each schedule file; regenerate with tools/gen_schedules.py --lock"]
        lines.extend(manifest_lines(out))
        (out / MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"locked {out / MANIFEST_NAME} ({len(lines) - 1} entries)")
    return 0


def check(schedules: list[Schedule], out: pathlib.Path) -> int:
    problems: list[str] = []
    expected_names = {f"{s.name}.json" for s in schedules}
    for schedule in schedules:
        path = out / f"{schedule.name}.json"
        if not path.exists():
            problems.append(f"missing on disk: {path.name}")
            continue
        if path.read_text(encoding="utf-8") != schedule.to_json():
            problems.append(f"differs from generator: {path.name} (schedule digest {schedule.digest()[:16]})")
    on_disk = {p.name for p in out.glob("*.json")}
    for extra in sorted(on_disk - expected_names):
        problems.append(f"not produced by the generator: {extra}")
    manifest = read_manifest(out / MANIFEST_NAME)
    if not manifest:
        problems.append(f"no {MANIFEST_NAME} in {out}; run --lock")
    else:
        for name in sorted(on_disk):
            actual = file_digest(out / name)
            recorded = manifest.get(name)
            if recorded is None:
                problems.append(f"not in {MANIFEST_NAME}: {name}")
            elif recorded != actual:
                problems.append(f"{MANIFEST_NAME} mismatch: {name} recorded {recorded[:16]} actual {actual[:16]}")
        for name in sorted(set(manifest) - on_disk):
            problems.append(f"in {MANIFEST_NAME} but not on disk: {name}")
    if problems:
        print(f"schedule corpus check FAILED ({len(problems)} problem(s)):")
        for problem in problems:
            print("  " + problem)
        return 1
    print(f"schedule corpus check OK: {len(on_disk)} schedules match the generator and {MANIFEST_NAME}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"root seed (default {DEFAULT_SEED})")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "schedules", help="corpus directory")
    parser.add_argument("--lock", action="store_true", help=f"also write {MANIFEST_NAME}")
    parser.add_argument("--check", action="store_true", help="verify disk against generator and MANIFEST; write nothing")
    parser.add_argument("--list", action="store_true", help="print the schedule names and exit")
    args = parser.parse_args(argv)
    if args.lock and args.check:
        parser.error("--lock and --check are exclusive")
    schedules = generate(args.seed)
    if args.list:
        for schedule in schedules:
            print(schedule.summary())
        return 0
    if args.check:
        return check(schedules, args.out)
    return write(schedules, args.out, args.lock)


if __name__ == "__main__":
    sys.exit(main())
