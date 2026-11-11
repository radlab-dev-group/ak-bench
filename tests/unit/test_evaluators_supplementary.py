"""The supplementary evaluators of plan 16: diff, static analysis, custom Python.

Each is a signal, not a verdict on the task, so the tests check two things at
once: that the measurement is right, and that it never claims more than the
signal supports (a diff never passes; a finding never fails a task on its own).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset
from akbench.evaluators.diff import DiffEvaluator, changed_lines, overlap
from akbench.evaluators.engine import EvaluationVerdict, EvaluatorEngine
from akbench.evaluators.python_evaluator import PythonEvaluator
from akbench.evaluators.registry import default_registry
from akbench.evaluators.static_analysis import StaticAnalysisEvaluator

REPO_ROOT = Path(__file__).resolve().parents[2]
WORDCOUNT = "wordcount-001"


@pytest.fixture
def sample(tmp_path: Path) -> dict[str, Path]:
    """Clean and mutated copies of the wordcount sample, plus its planted defect."""
    repos = RepositoryManager(tmp_path / "repos")
    workspaces = WorkspaceManager(repos, tmp_path / "workspaces")
    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    loaded = dataset.require(WORDCOUNT)
    clean = workspaces.prepare(loaded.task, "clean", task_dir=loaded.path, apply_mutation=False)
    mutated = workspaces.prepare(loaded.task, "mutated", task_dir=loaded.path, apply_mutation=True)
    return {
        "clean": clean.path,
        "mutated": mutated.path,
        "reference": loaded.path / "mutations" / "mutation-001.patch",
    }


def test_changed_lines_reads_both_sides_of_the_comparison() -> None:
    patch = (
        REPO_ROOT / "datasets" / "bug_fix" / WORDCOUNT / "mutations" / "mutation-001.patch"
    ).read_text(encoding="utf-8")
    lines = changed_lines(patch)
    assert lines == {"src/wordcount/text.py": {10, 11}}
    assert overlap(lines, lines).score == 1.0
    assert overlap({"src/wordcount/text.py": {999}}, lines).score == 0.0


def test_diff_of_the_reference_with_itself_is_a_full_overlap(sample: dict[str, Path]) -> None:
    result = DiffEvaluator().evaluate(
        sample["mutated"],
        out_dir=sample["mutated"].parent / "diff-self",
        reference_patch=sample["reference"],
    )
    assert result.score == 1.0
    assert result.details["files_matched"] == ["src/wordcount/text.py"]
    assert result.raw and "produced diff" in result.raw


def test_diff_never_reports_a_pass(sample: dict[str, Path]) -> None:
    """A diff is evidence about the change; only tests may say `passed`."""
    evaluator = DiffEvaluator()
    identical = evaluator.evaluate(
        sample["mutated"],
        out_dir=sample["mutated"].parent / "a",
        reference_patch=sample["reference"],
    )
    unrelated = evaluator.evaluate(
        sample["clean"], out_dir=sample["mutated"].parent / "b", reference_patch=sample["reference"]
    )
    assert identical.verdict is EvaluationVerdict.PARTIAL
    assert unrelated.verdict is EvaluationVerdict.FAILED
    assert {identical.verdict, unrelated.verdict} != {EvaluationVerdict.PASSED}


def test_diff_reports_an_unusable_reference_as_an_error_not_a_zero(
    sample: dict[str, Path], tmp_path: Path
) -> None:
    evaluator = DiffEvaluator()
    missing = evaluator.evaluate(
        sample["clean"], out_dir=tmp_path / "missing", reference_patch=tmp_path / "nope.patch"
    )
    assert missing.verdict is EvaluationVerdict.EVALUATOR_ERROR
    assert "not found" in missing.details["reason"]

    bogus = tmp_path / "bogus.patch"
    bogus.write_text("not a patch at all\n", encoding="utf-8")
    inapplicable = evaluator.evaluate(
        sample["clean"], out_dir=tmp_path / "bogus", reference_patch=bogus
    )
    assert inapplicable.verdict is EvaluationVerdict.EVALUATOR_ERROR
    assert "changes no file" in inapplicable.details["reason"]

    not_a_checkout = evaluator.evaluate(
        tmp_path, out_dir=tmp_path / "not-git", reference_patch=sample["reference"]
    )
    assert not_a_checkout.verdict is EvaluationVerdict.EVALUATOR_ERROR
    assert "not a git checkout" in not_a_checkout.details["reason"]


def test_static_analysis_scores_clean_and_dirty_workspaces(
    sample: dict[str, Path], tmp_path: Path
) -> None:
    evaluator = StaticAnalysisEvaluator()
    clean = evaluator.evaluate(
        sample["clean"],
        out_dir=tmp_path / "clean",
        command=[sys.executable, "-c", "import json; print(json.dumps([]))"],
    )
    assert clean.verdict is EvaluationVerdict.PASSED
    assert clean.score == 1.0

    dirty = evaluator.evaluate(
        sample["clean"],
        out_dir=tmp_path / "dirty",
        command=[
            sys.executable,
            "-c",
            "import json; print(json.dumps([{'filename': 'a.py', 'code': 'F401'}]))",
        ],
    )
    assert dirty.verdict is EvaluationVerdict.PARTIAL
    assert dirty.score == 0.0
    assert dirty.details["codes"] == {"F401": 1}


def test_static_analysis_separates_a_broken_analyser_from_a_finding(
    sample: dict[str, Path], tmp_path: Path
) -> None:
    evaluator = StaticAnalysisEvaluator()

    misuse = evaluator.evaluate(
        sample["clean"],
        out_dir=tmp_path / "misuse",
        command=[sys.executable, "-c", "import sys; sys.stderr.write('bad option'); sys.exit(2)"],
    )
    assert misuse.verdict is EvaluationVerdict.EVALUATOR_ERROR

    missing = evaluator.evaluate(
        sample["clean"],
        out_dir=tmp_path / "missing",
        command=[sys.executable, "-m", "no_such_analyser_xyz"],
    )
    assert missing.verdict is EvaluationVerdict.INFRASTRUCTURE_ERROR

    timed_out = evaluator.evaluate(
        sample["clean"],
        out_dir=tmp_path / "timeout",
        command=[sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=0.3,
    )
    assert timed_out.verdict is EvaluationVerdict.TIMEOUT


def test_static_analysis_defaults_to_ruff(sample: dict[str, Path], tmp_path: Path) -> None:
    """The default command is ruff; if it is not installed the verdict says so."""
    available = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"], capture_output=True, check=False
    ).returncode == 0
    result = StaticAnalysisEvaluator().evaluate(sample["clean"], out_dir=tmp_path / "ruff")
    if available:
        assert result.verdict in {EvaluationVerdict.PASSED, EvaluationVerdict.PARTIAL}
        assert result.details["codes"] is not None
    else:
        assert result.verdict is EvaluationVerdict.INFRASTRUCTURE_ERROR


PASSING_SCRIPT = """
import argparse, json, pathlib
parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True)
parser.add_argument("--out-dir", required=True)
args = parser.parse_args()
(pathlib.Path(args.out_dir) / "evaluator-result.json").write_text(json.dumps(
    {"verdict": "passed", "score": 1.0, "passed": 1, "failed": 0, "total": 1,
     "details": {"saw": (pathlib.Path(args.workspace) / "pyproject.toml").is_file()}}
), encoding="utf-8")
"""


def test_python_evaluator_runs_a_task_script_and_reads_its_verdict(
    sample: dict[str, Path], tmp_path: Path
) -> None:
    script = tmp_path / "judge.py"
    script.write_text(PASSING_SCRIPT, encoding="utf-8")
    result = PythonEvaluator().evaluate(
        sample["clean"], out_dir=tmp_path / "out", script=script, timeout=120
    )
    assert result.verdict is EvaluationVerdict.PASSED
    assert result.score == 1.0
    assert result.details["saw"] is True


def test_python_evaluator_rejects_every_way_a_script_can_cheat(
    sample: dict[str, Path], tmp_path: Path
) -> None:
    evaluator = PythonEvaluator()

    silent = tmp_path / "silent.py"
    silent.write_text("", encoding="utf-8")
    wrote_nothing = evaluator.evaluate(
        sample["clean"], out_dir=tmp_path / "silent", script=silent
    )
    assert wrote_nothing.verdict is EvaluationVerdict.EVALUATOR_ERROR
    assert "without writing" in wrote_nothing.details["reason"]

    invented = tmp_path / "invented.py"
    invented.write_text(
        "import argparse, json, pathlib\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--workspace'); p.add_argument('--out-dir')\n"
        "a = p.parse_args()\n"
        "(pathlib.Path(a.out_dir) / 'evaluator-result.json').write_text("
        "json.dumps({'verdict': 'shiny'}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    unknown = evaluator.evaluate(sample["clean"], out_dir=tmp_path / "invented", script=invented)
    assert unknown.verdict is EvaluationVerdict.EVALUATOR_ERROR
    assert "unknown verdict" in unknown.details["reason"]

    claims_infrastructure = tmp_path / "infra.py"
    claims_infrastructure.write_text(
        "import argparse, json, pathlib\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--workspace'); p.add_argument('--out-dir')\n"
        "a = p.parse_args()\n"
        "(pathlib.Path(a.out_dir) / 'evaluator-result.json').write_text("
        "json.dumps({'verdict': 'infrastructure_error'}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    not_owed = evaluator.evaluate(
        sample["clean"], out_dir=tmp_path / "infra", script=claims_infrastructure
    )
    assert not_owed.verdict is EvaluationVerdict.EVALUATOR_ERROR
    assert "may not report" in not_owed.details["reason"]

    crashed = tmp_path / "crash.py"
    crashed.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    broken = evaluator.evaluate(sample["clean"], out_dir=tmp_path / "crash", script=crashed)
    assert broken.verdict is EvaluationVerdict.EVALUATOR_ERROR

    timed = tmp_path / "sleep.py"
    timed.write_text("import time; time.sleep(5)\n", encoding="utf-8")
    too_slow = evaluator.evaluate(
        sample["clean"], out_dir=tmp_path / "slow", script=timed, timeout=0.3
    )
    assert too_slow.verdict is EvaluationVerdict.TIMEOUT


def test_python_evaluator_never_judges_the_agents_own_workspace(
    sample: dict[str, Path], tmp_path: Path
) -> None:
    """The script sees a copy: it cannot rewrite what it is judging."""
    script = tmp_path / "tamper.py"
    script.write_text(
        "import argparse, json, pathlib\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--workspace'); p.add_argument('--out-dir')\n"
        "a = p.parse_args()\n"
        "(pathlib.Path(a.workspace) / 'tampered.txt').write_text('x', encoding='utf-8')\n"
        "(pathlib.Path(a.out_dir) / 'evaluator-result.json').write_text("
        "json.dumps({'verdict': 'passed'}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    workspace = sample["clean"]
    before = {path.name for path in workspace.iterdir()}
    PythonEvaluator().evaluate(workspace, out_dir=tmp_path / "out", script=script, timeout=120)
    assert {path.name for path in workspace.iterdir()} == before


def test_supplementary_evaluators_resolve_through_the_engine(
    sample: dict[str, Path], tmp_path: Path
) -> None:
    engine = EvaluatorEngine(default_registry())
    result = engine.evaluate(
        "diff_evaluator",
        sample["mutated"],
        out_dir=tmp_path / "engine",
        reference_patch=sample["reference"],
    )
    assert result.evaluator_id == "diff_evaluator"
    assert result.verdict in {EvaluationVerdict.PARTIAL, EvaluationVerdict.FAILED}
    assert json.dumps(result.as_dict())
