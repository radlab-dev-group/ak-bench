"""Fault schedules: what happens, and when.

A schedule is a JSON document (``schedules/*.json``) that fixes everything a
run needs except the code: the node set, the node and network options, the
seed, the length in ticks, and a list of *actions* with the tick they fire
at. Two runs of the same schedule on the same code produce the same trace;
``tools/reference_traces.py`` keeps the digests of the corpus and
``tools/gen_schedules.py`` regenerates the corpus itself from a seed.

Action kinds (closed; ``SPEC.md`` section 9):

====================  ======================================================
kind                  arguments
====================  ======================================================
``propose``           ``command`` (``op``, ``key``, ``value``, ``expect``);
                      offered to the current leader, retried every tick
                      until a leader accepts it, or ``give_up_after`` ticks
``workload``          ``count``, ``every``, ``key_prefix``, ``op``: expands
                      to ``count`` proposes spaced ``every`` ticks apart
``partition``         ``groups``: list of lists of node ids
``heal``              —
``isolate``           ``node``
``block`` / ``unblock`` ``src``, ``dst``, optional ``both`` (default true)
``crash``             ``node``
``restart``           ``node``
``skew``              ``node``, optional ``rate``, optional ``offset``
``network``           any of ``min_delay``, ``max_delay``, ``drop_rate``,
                      ``dup_rate``, ``dup_extra_delay``
====================  ======================================================

Actions at the same tick fire in file order. Validation is strict: an
unknown kind, a node that is not in the cluster, or a tick past the end of
the run is a :class:`~tidewater.errors.ScheduleError` at load time, not a
surprise at tick 7000.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from .errors import ScheduleError
from .network import NetworkOptions
from .node import NodeOptions
from .statemachine import OPERATIONS

ACTION_KINDS: tuple[str, ...] = (
    "propose", "workload", "partition", "heal", "isolate", "block", "unblock",
    "crash", "restart", "skew", "network",
)

_NODE_ACTIONS = ("isolate", "crash", "restart", "skew")

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Action:
    at: int
    kind: str
    args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"at": self.at, "kind": self.kind}
        out.update({k: self.args[k] for k in sorted(self.args)})
        return out

    def summary(self) -> str:
        args = " ".join(f"{k}={json.dumps(v, separators=(',', ':'))}" for k, v in sorted(self.args.items()))
        return f"@{self.at} {self.kind} {args}".rstrip()


@dataclass
class Schedule:
    name: str
    nodes: tuple[str, ...]
    seed: int
    ticks: int
    actions: list[Action] = field(default_factory=list)
    description: str = ""
    node_options: NodeOptions = field(default_factory=NodeOptions)
    network_options: NetworkOptions = field(default_factory=NetworkOptions)
    give_up_after: int = 0

    # -- validation ---------------------------------------------------------

    def validate(self) -> None:
        if not self.name or "/" in self.name:
            raise ScheduleError("a schedule needs a name without slashes")
        if len(self.nodes) < 1:
            raise ScheduleError("a schedule needs at least one node")
        if len(set(self.nodes)) != len(self.nodes):
            raise ScheduleError("node ids must be unique")
        if tuple(sorted(self.nodes)) != self.nodes:
            raise ScheduleError("nodes must be listed in sorted order so that iteration order is unambiguous")
        if self.ticks < 1:
            raise ScheduleError("ticks must be at least 1")
        if self.seed < 0:
            raise ScheduleError("seed must be non-negative")
        if self.give_up_after < 0:
            raise ScheduleError("give_up_after cannot be negative")
        if self.network_options.max_delay * 2 >= self.node_options.election_timeout:
            raise ScheduleError("max_delay * 2 must be below election_timeout, or no leader can keep followers")
        for action in self.actions:
            self._validate_action(action)

    def _validate_action(self, action: Action) -> None:
        if action.kind not in ACTION_KINDS:
            raise ScheduleError(f"unknown action kind {action.kind!r}; the schedule knows {ACTION_KINDS}")
        if action.at < 0 or action.at >= self.ticks:
            raise ScheduleError(f"action {action.summary()} is outside [0, {self.ticks})")
        args = action.args
        if action.kind in _NODE_ACTIONS:
            node = args.get("node")
            if node not in self.nodes:
                raise ScheduleError(f"action {action.summary()} names unknown node {node!r}")
        if action.kind == "skew":
            if "rate" not in args and "offset" not in args:
                raise ScheduleError("skew needs rate and/or offset")
            if "rate" in args and int(args["rate"]) < 1:
                raise ScheduleError("skew rate must be at least 1")
        if action.kind == "partition":
            groups = args.get("groups")
            if not isinstance(groups, list) or not groups:
                raise ScheduleError("partition needs a non-empty list of groups")
            seen: set[str] = set()
            for group in groups:
                for node in group:
                    if node not in self.nodes:
                        raise ScheduleError(f"partition names unknown node {node!r}")
                    if node in seen:
                        raise ScheduleError(f"partition lists {node!r} twice")
                    seen.add(node)
        if action.kind in ("block", "unblock"):
            for key in ("src", "dst"):
                if args.get(key) not in self.nodes:
                    raise ScheduleError(f"{action.kind} needs src and dst that are cluster nodes")
        if action.kind == "propose":
            command = args.get("command")
            if not isinstance(command, dict) or command.get("op") not in OPERATIONS or not command.get("key"):
                raise ScheduleError(f"propose needs a command with op in {OPERATIONS} and a key")
        if action.kind == "workload":
            if int(args.get("count", 0)) < 1 or int(args.get("every", 0)) < 1:
                raise ScheduleError("workload needs count >= 1 and every >= 1")
            if args.get("op", "set") not in OPERATIONS:
                raise ScheduleError(f"workload op must be one of {OPERATIONS}")
            last = action.at + (int(args["count"]) - 1) * int(args["every"])
            if last >= self.ticks:
                raise ScheduleError(f"workload {action.summary()} runs past the end of the schedule")
        if action.kind == "network":
            try:
                self.network_options.replace(**{k: v for k, v in args.items()})
            except Exception as exc:  # ConfigurationError or TypeError
                raise ScheduleError(f"network action is invalid: {exc}") from exc

    # -- expansion ----------------------------------------------------------

    def expanded_actions(self) -> list[Action]:
        """Actions with every ``workload`` unrolled into ``propose`` actions,
        sorted by tick with a stable sort so file order is kept within a tick."""

        out: list[Action] = []
        for action in self.actions:
            if action.kind != "workload":
                out.append(action)
                continue
            count = int(action.args["count"])
            every = int(action.args["every"])
            prefix = action.args.get("key_prefix", "k")
            op = action.args.get("op", "set")
            client = action.args.get("client", f"w{action.at}")
            keys = int(action.args.get("keys", 0))
            for i in range(count):
                key = f"{prefix}{i % keys if keys else i}"
                command: dict[str, Any] = {"op": op, "key": key, "client": client, "seq": i + 1}
                if op in ("set", "cas"):
                    command["value"] = f"v{action.at}.{i}"
                if op == "cas":
                    command["expect"] = action.args.get("expect", "")
                if op == "incr":
                    command["value"] = str(action.args.get("amount", 1))
                out.append(Action(at=action.at + i * every, kind="propose", args={"command": command}))
        out.sort(key=lambda a: a.at)
        return out

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "description": self.description,
            "nodes": list(self.nodes),
            "seed": self.seed,
            "ticks": self.ticks,
            "give_up_after": self.give_up_after,
            "options": self.node_options.to_dict(),
            "network": self.network_options.to_dict(),
            "actions": [a.to_dict() for a in self.actions],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"

    def digest(self) -> str:
        """SHA-256 of the canonical form; what ``schedules/MANIFEST`` records."""

        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def summary(self) -> str:
        return (
            f"{self.name}: {len(self.nodes)} nodes, seed {self.seed}, {self.ticks} ticks, "
            f"{len(self.actions)} actions ({len(self.expanded_actions())} expanded)"
        )


def schedule_from_dict(data: dict[str, Any]) -> Schedule:
    try:
        schema = int(data.get("schema", SCHEMA_VERSION))
        if schema != SCHEMA_VERSION:
            raise ScheduleError(f"unsupported schedule schema {schema}; this build reads {SCHEMA_VERSION}")
        nodes = tuple(str(n) for n in data["nodes"])
        node_options = NodeOptions(**data.get("options", {}))
        network_options = NetworkOptions(**data.get("network", {}))
        actions = []
        for raw in data.get("actions", []):
            raw = dict(raw)
            at = int(raw.pop("at"))
            kind = str(raw.pop("kind"))
            actions.append(Action(at=at, kind=kind, args=raw))
        schedule = Schedule(
            name=str(data["name"]),
            description=str(data.get("description", "")),
            nodes=nodes,
            seed=int(data["seed"]),
            ticks=int(data["ticks"]),
            give_up_after=int(data.get("give_up_after", 0)),
            node_options=node_options,
            network_options=network_options,
            actions=actions,
        )
    except ScheduleError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ScheduleError(f"malformed schedule: {exc}") from exc
    except Exception as exc:  # ConfigurationError from the option classes
        raise ScheduleError(f"invalid schedule options: {exc}") from exc
    schedule.validate()
    return schedule


def load_schedule(path: str | pathlib.Path) -> Schedule:
    path = pathlib.Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScheduleError(f"cannot read schedule {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ScheduleError(f"{path} is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ScheduleError(f"{path}: a schedule is a JSON object")
    return schedule_from_dict(data)


def save_schedule(schedule: Schedule, path: str | pathlib.Path) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schedule.to_json(), encoding="utf-8")


def load_corpus(directory: str | pathlib.Path) -> list[Schedule]:
    """Every ``*.json`` in ``directory``, sorted by file name."""

    directory = pathlib.Path(directory)
    return [load_schedule(p) for p in sorted(directory.glob("*.json"))]


def file_digest(path: str | pathlib.Path) -> str:
    """SHA-256 of the file bytes. ``MANIFEST`` records this one, so that a
    reformatted but semantically identical file still shows up as changed —
    the corpus is generated, and hand edits are the thing to catch."""

    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def nodes_named(count: int, prefix: str = "n") -> tuple[str, ...]:
    if count < 1:
        raise ScheduleError("a cluster has at least one node")
    return tuple(f"{prefix}{i}" for i in range(1, count + 1))


def actions_sorted(actions: Iterable[Action]) -> list[Action]:
    return sorted(actions, key=lambda a: a.at)
