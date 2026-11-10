"""The repository tools and the ``python -m tidewater`` driver."""

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from tidewater.cli import main as cli_main

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
FAST_SCHEDULE = "three-node-minority-crash"


def run_tool(name, *args, cwd=ROOT):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run([sys.executable, str(TOOLS / name), *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


def test_schedule_corpus_matches_generator_and_manifest():
    result = run_tool("gen_schedules.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "13 schedules" in result.stdout
    assert len(list((ROOT / "schedules").glob("*.json"))) == 13
    assert (ROOT / "schedules" / "MANIFEST").exists()


def test_gen_schedules_lock_and_check_detect_hand_edits(tmp_path):
    out = tmp_path / "corpus"
    assert run_tool("gen_schedules.py", "--out", str(out)).returncode == 0
    check = run_tool("gen_schedules.py", "--out", str(out), "--check")
    assert check.returncode == 1 and "no MANIFEST" in check.stdout
    assert run_tool("gen_schedules.py", "--out", str(out), "--lock").returncode == 0
    assert run_tool("gen_schedules.py", "--out", str(out), "--check").returncode == 0
    victim = out / "baseline-steady.json"
    data = json.loads(victim.read_text())
    data["ticks"] += 1
    victim.write_text(json.dumps(data, indent=2) + "\n")
    check = run_tool("gen_schedules.py", "--out", str(out), "--check")
    assert check.returncode == 1
    assert "differs from generator: baseline-steady.json" in check.stdout
    assert "MANIFEST mismatch: baseline-steady.json" in check.stdout
    other = run_tool("gen_schedules.py", "--out", str(tmp_path / "other"), "--seed", "3", "--lock")
    assert other.returncode == 0
    assert (tmp_path / "other" / "MANIFEST").read_text() != (out / "MANIFEST").read_text()


def test_reference_traces_check_passes_for_a_fast_schedule_and_detects_changes(tmp_path):
    result = run_tool("reference_traces.py", "--check", "--only", FAST_SCHEDULE, "-v")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ok       {FAST_SCHEDULE}" in result.stdout
    # A tampered digest file is reported as a mismatch with tick numbers to start from.
    traces = tmp_path / "traces"
    traces.mkdir()
    original = (ROOT / "traces" / f"{FAST_SCHEDULE}.digest").read_text()
    tampered = "\n".join(
        ("trace_digest     " + "0" * 64) if line.startswith("trace_digest") else line
        for line in original.splitlines()
    ) + "\n"
    (traces / f"{FAST_SCHEDULE}.digest").write_text(tampered)
    result = run_tool("reference_traces.py", "--check", "--only", FAST_SCHEDULE, "--traces", str(traces))
    assert result.returncode == 1
    assert f"MISMATCH {FAST_SCHEDULE}" in result.stdout and "last digest events" in result.stdout
    # A missing digest is reported as MISSING.
    result = run_tool("reference_traces.py", "--check", "--only", "baseline-steady", "--traces", str(traces))
    assert result.returncode == 1 and "MISSING  baseline-steady" in result.stdout


def test_reference_traces_write_and_replay_round_trip(tmp_path):
    traces = tmp_path / "traces"
    full = tmp_path / "full"
    result = run_tool("reference_traces.py", "--only", FAST_SCHEDULE, "--traces", str(traces), "--write-traces", str(full))
    assert result.returncode == 0, result.stdout + result.stderr
    digest_file = traces / f"{FAST_SCHEDULE}.digest"
    assert digest_file.exists() and (full / f"{FAST_SCHEDULE}.jsonl").exists()
    assert digest_file.read_text() == (ROOT / "traces" / f"{FAST_SCHEDULE}.digest").read_text()
    schedule = ROOT / "schedules" / f"{FAST_SCHEDULE}.json"
    replay = run_tool("replay_trace.py", str(schedule), "--reference", str(digest_file))
    assert replay.returncode == 0 and "match" in replay.stdout
    replay = run_tool("replay_trace.py", str(schedule), "--reference-trace", str(full / f"{FAST_SCHEDULE}.jsonl"), "--all")
    assert replay.returncode == 0 and "all events" in replay.stdout
    # A different seed diverges, and the tool names the first divergent digest event.
    replay = run_tool("replay_trace.py", str(schedule), "--seed", "1",
                      "--reference-trace", str(full / f"{FAST_SCHEDULE}.jsonl"))
    assert replay.returncode == 1 and "first divergence at position" in replay.stdout
    replay = run_tool("replay_trace.py", str(schedule), "--seed", "1", "--reference", str(digest_file))
    assert replay.returncode == 1 and "MISMATCH" in replay.stdout


def test_cli_run_describe_and_digest(tmp_path, capsys):
    schedule = ROOT / "schedules" / f"{FAST_SCHEDULE}.json"
    out = tmp_path / "run.jsonl"
    code = cli_main(["run", str(schedule), "--ticks", "600", "--trace", str(out), "--json"])
    assert code == 0
    summary = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert summary["ticks"] == 600 and summary["violation"] is None
    assert out.exists() and summary["events"] == sum(1 for _ in out.open())

    assert cli_main(["digest", str(out), "-v"]) == 0
    text = capsys.readouterr().out
    assert text.splitlines()[0] == summary["digest"]

    assert cli_main(["describe", str(schedule), "--expand"]) == 0
    text = capsys.readouterr().out
    assert FAST_SCHEDULE in text and "@300 crash" in text and "propose" in text

    assert cli_main(["run", str(schedule), "--ticks", "200", "--text", "--quiet"]) == 0
    text = capsys.readouterr().out
    assert "t=000000" in text and len(text.splitlines()) > 100

    missing = tmp_path / "nope.json"
    assert cli_main(["run", str(missing)]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_runs_as_a_module_and_corpus_traces_are_long(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run([sys.executable, "-m", "tidewater", "run",
                             str(ROOT / "schedules" / f"{FAST_SCHEDULE}.json"), "--json"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["events"] > 2000
    assert len(summary["leaders_by_term"]) >= 1
    recorded = (ROOT / "traces" / f"{FAST_SCHEDULE}.digest").read_text()
    assert summary["digest"] in recorded
