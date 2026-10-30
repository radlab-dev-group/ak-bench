#!/usr/bin/env python3
"""A stub agent that *fixes* the defect, to exercise a successful run.

Used by the orchestrator tests: it behaves like the Codex CLI stub (same event
stream, same rollout, same ``-o`` file) but it also repairs the known mutation
in the wordcount sample, so an end-to-end run reaches a passing evaluation.

The point is not to simulate intelligence — it is to prove that the generic
orchestrator, adapter contract, workspace manager and evaluator produce a
``passed`` verdict when the work is done, without any test knowing what Codex is.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VERSION = "codex-cli 0.0.0-fixer"
TARGET = Path("src/wordcount/text.py")
DEFECT = 'split(" ")'
FIX = "split()"


def flag_value(argv: list[str], flag: str, default: str | None = None) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else default


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def write_rollout(home: str) -> None:
    session_dir = Path(home) / "sessions" / "2026" / "10" / "30"
    session_dir.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "session_meta", "payload": {"cli_version": VERSION, "cwd": os.getcwd()}},
        {"type": "turn_context", "payload": {"model": "stub-model-alias", "cwd": os.getcwd()}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "apply_patch"}},
        {
            "type": "token_usage_record",
            "payload": {
                "thread_token_usage": {
                    "input_tokens": 90,
                    "cached_input_tokens": 10,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 4,
                    "total_tokens": 110,
                }
            },
        },
    ]
    with open(session_dir / "rollout-fixer.jsonl", "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def apply_fix(cwd: str) -> bool:
    path = Path(cwd) / TARGET
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if DEFECT not in text:
        return False
    path.write_text(text.replace(DEFECT, FIX), encoding="utf-8")
    return True


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print(VERSION)
        return 0

    cwd = flag_value(argv, "--cd", os.getcwd())
    last_message = flag_value(argv, "-o")
    log = os.environ.get("STUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "cwd": cwd}) + "\n")

    emit({"type": "thread.started", "thread_id": "stub-fixer-1"})
    fixed = apply_fix(cwd)
    message = "Repaired the whitespace handling." if fixed else "Nothing to fix."
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": message}})
    emit(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 90,
                "cached_input_tokens": 10,
                "output_tokens": 20,
                "reasoning_output_tokens": 4,
                "total_tokens": 110,
            },
        }
    )
    if last_message:
        Path(last_message).write_text(message, encoding="utf-8")
    home = os.environ.get("CODEX_HOME")
    if home:
        write_rollout(home)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
