"""The command line driver.

The CLI is a thin shell over :class:`~atlas.store.Atlas`. It exists for two
reasons: an operator needs to ask a live store what it thinks, and a benchmark
needs one deterministic way to start a store, run a scenario against it, and
report the answer in a machine-readable form.

Exit codes are stable: ``0`` success, ``1`` a store error, ``2`` a usage
error. A command that cannot tell the two apart is a command an automation
cannot use.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from .config import build as build_config
from .errors import AtlasError
from .store import AtlasBuilder

EXIT_OK = 0
EXIT_STORE_ERROR = 1
EXIT_USAGE = 2


def _store(arguments, root: pathlib.Path):
    config = build_config(
        path=arguments.config or "none.toml",
        values={"shards": arguments.shards, "vnodes": arguments.vnodes},
    )
    builder = AtlasBuilder().config(config).root(root)
    if arguments.replicas:
        builder.replicas(*arguments.replicas.split(","))
    return builder.build()


def _emit(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True, default=str))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
        return
    print(payload)


def command_put(arguments) -> int:
    store = _store(arguments, pathlib.Path(arguments.root))
    result = store.put(arguments.key, json.loads(arguments.value) if arguments.value.startswith(("{", "[", '"')) else arguments.value)
    _emit(
        {
            "key": result.key,
            "generation": result.record.generation,
            "lsn": result.record.lsn,
            "replicas": list(result.replicas),
        },
        as_json=arguments.json,
    )
    return EXIT_OK


def command_get(arguments) -> int:
    store = _store(arguments, pathlib.Path(arguments.root))
    record = store.get(arguments.key)
    if record is None:
        _emit({"key": arguments.key, "found": False}, as_json=arguments.json)
        return EXIT_STORE_ERROR
    _emit(
        {
            "key": record.key,
            "value": record.value,
            "generation": record.generation,
            "lsn": record.lsn,
            "vector": record.vector.render(),
        },
        as_json=arguments.json,
    )
    return EXIT_OK


def command_delete(arguments) -> int:
    store = _store(arguments, pathlib.Path(arguments.root))
    result = store.delete(arguments.key)
    _emit({"key": result.key, "generation": result.record.generation}, as_json=arguments.json)
    return EXIT_OK


def command_stats(arguments) -> int:
    store = _store(arguments, pathlib.Path(arguments.root))
    _emit(store.stats(), as_json=arguments.json)
    return EXIT_OK


def command_recover(arguments) -> int:
    store = _store(arguments, pathlib.Path(arguments.root))
    _emit(store.recover(), as_json=arguments.json)
    return EXIT_OK


def command_compact(arguments) -> int:
    store = _store(arguments, pathlib.Path(arguments.root))
    _emit(store.compact(), as_json=arguments.json)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description=__doc__.splitlines()[0])
    parser.add_argument("--root", default="./atlas-data", help="store directory")
    parser.add_argument("--config", default=None, help="configuration file")
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--vnodes", type=int, default=64)
    parser.add_argument("--replicas", default="", help="comma separated replica names")
    parser.add_argument("--json", action="store_true", help="machine readable output")
    actions = parser.add_subparsers(dest="action", required=True)

    put = actions.add_parser("put", help="write a key")
    put.add_argument("key")
    put.add_argument("value")
    put.set_defaults(handler=command_put)

    get = actions.add_parser("get", help="read a key")
    get.add_argument("key")
    get.set_defaults(handler=command_get)

    delete = actions.add_parser("delete", help="delete a key")
    delete.add_argument("key")
    delete.set_defaults(handler=command_delete)

    stats = actions.add_parser("stats", help="cluster summary")
    stats.set_defaults(handler=command_stats)

    recover = actions.add_parser("recover", help="reopen from disk and report")
    recover.set_defaults(handler=command_recover)

    compact = actions.add_parser("compact", help="snapshot every shard")
    compact.set_defaults(handler=command_compact)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return arguments.handler(arguments)
    except AtlasError as exc:
        print(f"error[{exc.code}]: {exc}", file=sys.stderr)
        return EXIT_STORE_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
