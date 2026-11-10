"""The schema tools: the generated tables are locked and the goldens are recorded."""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run_tool(name, *arguments):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / name), *arguments],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_generated_tables_are_locked():
    completed = run_tool("gen_tables.py", "--check")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "locked" in completed.stdout


def test_the_generated_tables_are_the_generator_output():
    completed = run_tool("gen_tables.py", "--stdout")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == (ROOT / "src" / "atlas" / "tables.py").read_text(encoding="utf-8")


def test_a_golden_is_recorded_for_every_row_layout_and_every_declared_index():
    import atlas.tables as tables

    recorded = json.loads((ROOT / "schema" / "goldens" / "GOLDENS.json").read_text(encoding="utf-8"))
    for version in ("v1", "v2", "v3"):
        assert f"records-{version}" in recorded
    for name, _columns, _unique, _where in tables.INDEXES:
        assert f"index-{name}" in recorded
    for name in recorded:
        assert (ROOT / "schema" / "goldens" / f"{name}.frame").exists(), name
