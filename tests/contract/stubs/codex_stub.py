#!/usr/bin/env python3
"""Stub of the Codex CLI, so the adapter can be tested without an agent.

It reproduces only the interface facts the adapter relies on (verified in
``docs/AGENT_INTEGRATION.md``):

- ``--json`` prints a flat event stream on stdout;
- ``-o FILE`` receives the final agent message;
- the session rollout lands in ``$CODEX_HOME/sessions/**/rollout-*.jsonl``;
- ``--version`` prints the CLI version;
- SIGINT interrupts a turn and the process then exits.

Behaviour is selected with ``--stub-behaviour`` so one stub covers every
contract test, and each invocation is appended as JSON to ``$STUB_LOG`` so a
test can assert what the adapter actually asked for.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

VERSION = "codex-cli 0.0.0-stub"


def flag_value(argv: list[str], flag: str, default: str | None = None) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else default


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def write_rollout(home: str, *, usage: bool) -> None:
    session_dir = Path(home) / "sessions" / "2026" / "10" / "30"
    session_dir.mkdir(parents=True, exist_ok=True)
    rollout = session_dir / "rollout-stub.jsonl"
    records = [
        {
            "type": "session_meta",
            "payload": {
                "cli_version": VERSION,
                "model_provider": "akbench",
                "cwd": os.getcwd(),
            },
        },
        {
            "type": "turn_context",
            "payload": {
                "model": "stub-model-alias",
                "sandbox_policy": {"type": "workspace-write"},
                "cwd": os.getcwd(),
            },
        },
        {"type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "apply_patch"}},
    ]
    if usage:
        records.append(
            {
                "type": "token_usage_record",
                "payload": {
                    "thread_token_usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 40,
                        "output_tokens": 30,
                        "reasoning_output_tokens": 6,
                        "total_tokens": 150,
                    }
                },
            }
        )
    with open(rollout, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print(VERSION)
        return 0

    behaviour = flag_value(argv, "--stub-behaviour", "complete")
    assert behaviour is not None
    last_message = flag_value(argv, "-o")
    cwd = flag_value(argv, "--cd", os.getcwd())
    prompt = argv[-1]

    log = os.environ.get("STUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "argv": argv,
                        "cwd": cwd,
                        "prompt": prompt,
                        "codex_home": os.environ.get("CODEX_HOME"),
                        "behaviour": behaviour,
                    }
                )
                + "\n"
            )

    home = os.environ.get("CODEX_HOME")

    if behaviour == "hang":
        stopped: dict[str, bool] = {}


        def interrupt(signum, frame) -> None:
            stopped["interrupted"] = True

        signal.signal(signal.SIGINT, interrupt)
        deadline = time.time() + 30
        while time.time() < deadline and not stopped:
            time.sleep(0.05)
        if stopped:
            if last_message:
                Path(last_message).write_text("Interrupted.", encoding="utf-8")
            return 0
        return 1

    emit({"type": "thread.started", "thread_id": "stub-thread-1"})

    if behaviour == "infra_error":
        sys.stderr.write("ERROR codex_core::client: stream disconnected: connection refused\n")
        return 1

    if behaviour == "fail":
        emit({"type": "error", "message": "stub turn could not be completed"})
        sys.stderr.write("stub reported a failure\n")
        return 1

    emit(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Stub finished the task."},
        }
    )
    if behaviour != "no_usage":
        emit(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 40,
                    "output_tokens": 25,
                    "reasoning_output_tokens": 5,
                    "total_tokens": 125,
                },
            }
        )
    if last_message:
        Path(last_message).write_text("Stub finished the task.", encoding="utf-8")
    if home and behaviour != "no_rollout":
        write_rollout(home, usage=behaviour != "no_usage")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
