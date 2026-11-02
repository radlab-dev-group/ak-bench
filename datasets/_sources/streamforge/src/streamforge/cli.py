"""JSON-lines driver: python -m streamforge.cli CONFIG [--restore CHECKPOINT]."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .config import Pipeline, Window
from .model import Event
from .runtime import Processor


def dispatch(processor: Processor, command: dict) -> list:
    operation = command["op"]
    if operation == "event":
        return processor.ingest(Event(**command["event"]))
    if operation == "watermark":
        return processor.advance(command["partition"], command["timestamp"])
    if operation == "idle":
        return processor.mark_idle(command["partition"], command.get("idle", True))
    if operation == "checkpoint":
        processor.checkpoint(Path(command["path"]))
        return []
    raise ValueError("unknown command")


def main() -> None:
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--restore", type=Path)
    arguments = parser.parse_args()
    document = json.loads(arguments.config.read_text())
    pipeline = Pipeline(
        tuple(document["partitions"]),
        tuple(Window(**row) for row in document["windows"]),
        document.get("lateness", 0),
    )
    processor = (
        Processor.restore(pipeline, arguments.restore) if arguments.restore else Processor(pipeline)
    )
    for line in sys.stdin:
        if line.strip():
            changes = dispatch(processor, json.loads(line))
            print(json.dumps([asdict(change) for change in changes], sort_keys=True))


if __name__ == "__main__":
    main()
