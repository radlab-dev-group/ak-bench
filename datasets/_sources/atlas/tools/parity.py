#!/usr/bin/env python3
"""Differential parity harness: store versus in-memory model.

Run it as ``python tools/parity.py`` with ``PYTHONPATH=src``. It generates
deterministic operation sequences, applies them to the real store and to a
deliberately naive in-memory model, and reports the first key on which the
two disagree.

The model is the point. It is not "the store but simpler"; it is what a
reader who never met fencing, torn tails or a rebalance would expect the store
to do. Where the two disagree, either the store has a defect or the model has
run into a rule the store documents and the model does not know about, and
telling those two apart is the whole exercise. Two consequences of that:

* a divergence is **not** automatically a bug, and the report says which rules
  the model knows, so the reader can see when a difference is documented
  behaviour rather than a defect;
* the harness is minimal by design, and its switches change what it can find.
  ``--help`` lists them and nothing else documents them; the defaults are a
  starting point, not a complete check.

The exit status is 0 when no divergence was found and 1 when there was one,
so it composes in a shell.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from atlas.config import build as build_config  # noqa: E402
from atlas.errors import AtlasError  # noqa: E402
from atlas.store import AtlasBuilder  # noqa: E402

#: What the naive model understands. A divergence on a rule listed here is a
#: store defect; a divergence on a rule that is not here is the model's limit.
MODEL_RULES = (
    "last-write-wins by generation",
    "a delete removes the key",
    "a key belongs to one owner",
)

OPERATIONS = ("put", "get", "delete", "bump", "compact", "recover", "rebalance")


class Model:
    """The expectation of a reader who knows nothing about the protocol."""

    def __init__(self) -> None:
        self.keys: dict[str, object] = {}

    def put(self, key, value):
        self.keys[key] = value

    def get(self, key):
        return self.keys.get(key)

    def delete(self, key):
        self.keys.pop(key, None)
        return None

    def bump(self, key, amount):
        current = self.keys.get(key)
        if isinstance(current, dict) and "count" in current:
            current = dict(current, count=current["count"] + amount)
        else:
            current = amount
        self.keys[key] = current
        return current

    def compact(self):
        return None

    def recover(self):
        return None

    def rebalance(self, *args):
        return None


def script(seed: int, length: int, keyspace: int):
    rng = random.Random(seed)
    for step in range(length):
        operation = rng.choices(OPERATIONS, weights=(28, 22, 8, 18, 6, 6, 2))[0]
        key = f"k{rng.randrange(keyspace)}"
        yield step, operation, key


def run(seed: int, length: int, keyspace: int, *, shards: int, replicas: int, vnodes: int,
        stop_after: int | None, shrink: bool, only: str | None):
    directory = pathlib.Path(tempfile.mkdtemp(prefix="atlas-parity-"))
    config = build_config(
        path="none.toml",
        env={},
        values={
            "shards": shards,
            "replication_factor": replicas,
            "read_consistency": (replicas // 2) + 1,
            "write_consistency": (replicas // 2) + 1,
            "vnodes": vnodes,
        },
    )
    store = AtlasBuilder().config(config).root(directory).build()
    model = Model()
    divergences = []
    executed = 0
    for step, operation, key in script(seed, length, keyspace):
        if only and operation != only:
            continue
        if stop_after is not None and step > stop_after:
            break
        try:
            if operation == "put":
                value = {"count": step, "seed": seed}
                store.put(key, value)
                model.put(key, value)
            elif operation == "bump":
                current = store.get(key)
                amount = (step % 7) + 1
                if current is None:
                    store.put(key, {"count": amount, "seed": seed})
                    model.put(key, {"count": amount, "seed": seed})
                else:
                    store.put(key, {"count": current.value["count"] + amount, "seed": seed})
                    model.bump(key, amount)
            elif operation == "get":
                expected = model.get(key)
                found = store.get(key)
                actual = found.value if found is not None else None
                if actual != expected:
                    divergences.append(
                        {
                            "step": step,
                            "operation": operation,
                            "key": key,
                            "model": expected,
                            "store": actual,
                            "shard": store.shard_of(key),
                            "owner": store.owner(key),
                        }
                    )
            elif operation == "delete":
                if store.get(key) is not None:
                    store.delete(key)
                model.delete(key)
            elif operation == "compact":
                store.compact()
            elif operation == "recover":
                store.recover()
            elif operation == "rebalance":
                names = sorted(store.nodes)
                target = names[1:] + [f"{names[0]}-new"]
                store.rebalance(target)
        except AtlasError as exc:
            divergences.append(
                {"step": step, "operation": operation, "key": key, "error": f"{type(exc).__name__}: {exc}"}
            )
        executed += 1
        if divergences and shrink:
            break
    return {
        "seed": seed,
        "steps": executed,
        "model_rules": list(MODEL_RULES),
        "divergences": divergences,
        "clean": not divergences,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("--seed", type=int, default=1, help="generation seed")
    parser.add_argument("--length", type=int, default=200, help="operations to run")
    parser.add_argument("--keyspace", type=int, default=12, help="distinct keys touched")
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--replicas", type=int, default=3)
    parser.add_argument("--vnodes", type=int, default=16)
    parser.add_argument("--stop-after", type=int, default=None, help="stop at this step")
    parser.add_argument("--shrink", action="store_true", help="stop at the first divergence")
    parser.add_argument("--only", default=None, help="run a single operation class")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)

    report = run(
        arguments.seed,
        arguments.length,
        arguments.keyspace,
        shards=arguments.shards,
        replicas=arguments.replicas,
        vnodes=arguments.vnodes,
        stop_after=arguments.stop_after,
        shrink=arguments.shrink,
        only=arguments.only,
    )
    if arguments.json:
        print(json.dumps(report, sort_keys=True, default=str))
    else:
        print(f"seed={report['seed']} steps={report['steps']} clean={report['clean']}")
        for item in report["divergences"][:20]:
            print("  " + json.dumps(item, sort_keys=True, default=str))
        if report["clean"]:
            print("  the store agreed with the model on every checked read")
        else:
            print(f"  model rules: {', '.join(report['model_rules'])}")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
