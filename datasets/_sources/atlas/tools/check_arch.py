#!/usr/bin/env python3
"""Check the layering of the store against the boundaries the design drew.

::

    python tools/check_arch.py
    python tools/check_arch.py --layers storage,replication,cluster
    python tools/check_arch.py --rules /tmp/layers.json

Every module of the store belongs to a layer, and a layer may import only from
itself and from layers below it. The layers, lowest to highest, are the
foundation (errors, values, the version clock, the registries), the
configuration and placement (config, membership, epochs, the ring, placement
plans), the durable half (the WAL, snapshots, the memtable, one shard's
storage), the protocol (fencing, repair, replication, anti-entropy,
migration, rebalance), and the public surface (the store API, transactions,
the command line). A module in a higher layer that reaches into a lower one
is the ordinary direction, and it is allowed; the reverse — the storage layer
importing the protocol, the protocol importing the API — is a violation,
because it is the direction in which a refactor quietly moves state up the
stack and leaves the design to explain why.

The layer map is the tool's own, and ``--rules`` points at a JSON document
that replaces it. That is how a task says "the design you are asked to build
has these boundaries" without the tool being changed: the boundaries are data,
the check is the same check, and the exit code is the same exit code.

Exit status: 0 when every import respects the layers, 1 when one does not,
2 when the rules are not a document the tool can read.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "atlas"

#: The layers, lowest to highest. A module may import from its own layer or
#: any layer below it; the reverse is the violation.
DEFAULT_LAYERS: dict[str, int] = {
    "errors": 0,
    "values": 0,
    "vclock": 0,
    "registry": 0,
    "audit": 0,
    "lineage": 0,
    "schema": 0,
    "tables": 0,
    "codec": 0,
    "clock": 1,
    "config": 1,
    "membership": 1,
    "ring": 1,
    "placement": 1,
    "faults": 1,
    "wal": 2,
    "snapshot": 2,
    "memtable": 2,
    "storage": 2,
    "retention": 2,
    "evolution": 2,
    "fencing": 3,
    "repair": 3,
    "replication": 3,
    "antientropy": 3,
    "migration": 3,
    "rebalance": 3,
    "transaction": 3,
    "cache": 3,
    "store": 4,
    "cli": 4,
    "compat": 4,
}


def modules_of(rules: dict[str, int]) -> list[tuple[pathlib.Path, str]]:
    """Every module and the layer it sits in, by the rules' name for it."""

    found: list[tuple[pathlib.Path, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        name = path.name[: -len(".py")]
        if path.parent.name == "vendor":
            name = f"vendor.{name}"
        if name not in rules:
            continue
        found.append((path, name))
    return found


def imports_of(path: pathlib.Path) -> list[str]:
    """The atlas modules this file imports, by the checker's name for them."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level and node.module:
            target = node.module
        elif isinstance(node, ast.Import):
            target = next((alias.name for alias in node.names if alias.name), "")
            if not target.startswith("atlas"):
                continue
            target = target.split(".")[1]
        else:
            continue
        if not target:
            continue
        target = target.split(".")[0]
        if target == "atlas":
            continue
        names.add(target)
    return sorted(names)


def check(rules: dict[str, int]) -> list[str]:
    """Every import that goes up the stack, as a line a reader can act on."""

    violations: list[str] = []
    for path, name in modules_of(rules):
        for imported in imports_of(path):
            if imported not in rules:
                continue
            if rules[imported] > rules[name]:
                violations.append(
                    f"{path.relative_to(ROOT)}: {name} (layer {rules[name]}) "
                    f"imports {imported} (layer {rules[imported]})"
                )
    return sorted(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_arch", description=__doc__.splitlines()[0])
    parser.add_argument("--rules", type=pathlib.Path, help="a JSON layer map that replaces the built-in one")
    parser.add_argument("--layers", help="comma-separated layer names to limit the report to")
    args = parser.parse_args(argv)

    rules = dict(DEFAULT_LAYERS)
    if args.rules is not None:
        try:
            loaded = json.loads(args.rules.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"check_arch: cannot read rules {args.rules}: {exc}", file=sys.stderr)
            return 2
        if not isinstance(loaded, dict):
            print("check_arch: a rules document is an object of module name to layer", file=sys.stderr)
            return 2
        for name, layer in loaded.items():
            if not isinstance(layer, int):
                print(f"check_arch: layer for {name} is not a number: {layer!r}", file=sys.stderr)
                return 2
            rules[name] = layer

    violations = check(rules)
    if args.layers:
        wanted = {name.strip() for name in args.layers.split(",") if name.strip()}
        violations = [line for line in violations if any(name in line for name in wanted)]

    for line in violations:
        print(f"violation  {line}")
    if violations:
        print(f"check_arch: {len(violations)} violation(s)")
        return 1
    print(f"check_arch: {len(modules_of(rules))} modules, no layer violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
