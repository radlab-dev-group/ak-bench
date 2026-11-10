#!/usr/bin/env python3
"""Verify the golden frames under ``schema/goldens/`` against the code.

A golden is a sha256 digest, recorded in ``schema/goldens/GOLDENS.json``, of
bytes the code must be able to reproduce from the fixed rows in
``schema/goldens/rows.json``:

* ``records-v<n>`` — every golden row encoded as one ``PUT`` frame at layout
  ``v<n>`` (:func:`atlas.evolution.frame_for`), concatenated;
* ``index-<name>`` — the projection of the declared index ``<name>`` over the
  golden rows, as one ``CONTROL`` frame (:func:`atlas.evolution.index_frame`).

The expected bytes are also kept beside the digest as ``<name>.frame`` so a
mismatch can be inspected with a hex dump; the digest is what is compared.

::

    python tools/verify_goldens.py                     # verify everything
    python tools/verify_goldens.py --family records    # only the row layouts
    python tools/verify_goldens.py --family indexes    # only the indexes
    python tools/verify_goldens.py --write index-by_x  # record a new golden
    python tools/verify_goldens.py --list

Every outcome is one line, and the lines are stable so a reader can grep
them::

    OK <name> <sha256>
    GoldenMismatch(<name>, expected=<sha256>, actual=<sha256>)
    NotImplemented(<name>)

The exit status is 0 only when every selected golden is ``OK``. The tool is
the second step of the procedure in ``docs/schema-evolution.md``; it never
rewrites ``GOLDENS.json`` unless asked to with ``--write``.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from atlas import evolution  # noqa: E402

GOLDENS_DIR = ROOT / "schema" / "goldens"
INDEX_FILE = "GOLDENS.json"


def load_index(directory: pathlib.Path) -> dict[str, str]:
    path = directory / INDEX_FILE
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def save_index(directory: pathlib.Path, index: dict[str, str]) -> None:
    ordered = {name: index[name] for name in sorted(index)}
    (directory / INDEX_FILE).write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")


def family_of(name: str) -> str:
    if name.startswith("records-"):
        return "records"
    if name.startswith("index-"):
        return "indexes"
    return "unknown"


def verify(directory: pathlib.Path, names: list[str], index: dict[str, str], rows) -> list[str]:
    lines: list[str] = []
    for name in names:
        expected = index.get(name)
        if expected is None:
            lines.append(f"GoldenMissing({name})")
            continue
        try:
            actual = evolution.sha256(evolution.golden_bytes(name, rows))
        except NotImplementedError:
            lines.append(f"NotImplemented({name})")
            continue
        if actual != expected:
            lines.append(f"GoldenMismatch({name}, expected={expected}, actual={actual})")
        else:
            lines.append(f"OK {name} {actual}")
    return lines


def write(directory: pathlib.Path, names: list[str], index: dict[str, str], rows) -> list[str]:
    lines: list[str] = []
    for name in names:
        data = evolution.golden_bytes(name, rows)
        digest = evolution.sha256(data)
        (directory / f"{name}.frame").write_bytes(data)
        index[name] = digest
        lines.append(f"WROTE {name} {digest}")
    save_index(directory, index)
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="verify_goldens.py")
    parser.add_argument("--goldens", type=pathlib.Path, default=GOLDENS_DIR)
    parser.add_argument("--family", choices=("all",) + evolution.GOLDEN_FAMILIES, default="all")
    parser.add_argument("--write", nargs="+", metavar="NAME", help="record these goldens from the code")
    parser.add_argument("--list", action="store_true")
    arguments = parser.parse_args(argv)

    directory: pathlib.Path = arguments.goldens
    index = load_index(directory)
    if arguments.list:
        for name in sorted(index):
            print(f"{name} {index[name]}")
        return 0
    rows = evolution.golden_rows(directory / "rows.json")
    if arguments.write:
        for line in write(directory, list(arguments.write), index, rows):
            print(line)
        return 0
    names = [
        name
        for name in sorted(index)
        if arguments.family == "all" or family_of(name) == arguments.family
    ]
    if not names:
        print(f"no goldens recorded for family {arguments.family!r}")
        return 1
    lines = verify(directory, names, index, rows)
    for line in lines:
        print(line)
    failed = [line for line in lines if not line.startswith("OK ")]
    if failed:
        print(f"{len(failed)} of {len(lines)} goldens did not verify; see docs/schema-evolution.md")
        return 1
    print(f"{len(lines)} goldens verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
