"""JSON-lines local operator interface; no background worker or wall clock."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .model import Lease
from .queue import Queue


def dispatch(queue: Queue, command: dict):
    operation = command.pop("op")
    if operation == "put":
        return queue.put(**command)
    if operation == "put_many":
        return queue.put_many(command["requests"])
    if operation == "reserve":
        return [asdict(token) for token in queue.reserve(**command)]
    if operation in {"ack", "release"}:
        command["lease"] = Lease(**command["lease"])
        return getattr(queue, operation)(**command)
    if operation == "reap":
        return queue.reap(**command)
    if operation == "compact":
        return queue.compact()
    if operation == "stats":
        return queue.stats()
    if operation == "export":
        return queue.export()
    raise ValueError("unknown command")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    queue = Queue(arguments.directory)
    for line in sys.stdin:
        if line.strip():
            print(json.dumps(dispatch(queue, json.loads(line)), sort_keys=True))


if __name__ == "__main__":
    main()
