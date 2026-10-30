"""The evaluator engine: verdicts, isolation and the separation of failures.

Uses the shipped wordcount sample (seed source + hidden tests) as the subject,
so the tests exercise the same code path the CLI does, without a network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset, TaskLoadError
from akbench.evaluators.engine import EvaluationVerdict, EvaluatorEngine
from akbench.evaluators.isolation import evaluation_sandbox
from akbench.evaluators.pytest_evaluator import PytestEvaluator
from akbench.evaluators.registry import default_registry

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sample_workspace(tmp_path: Path) -> dict[str, Path]:
    """Clean and mutated copies of the wordcount source, prepared like Phase 3."""
    repos = RepositoryManager(tmp_path / "repos")
    workspaces = WorkspaceManager(repos, tmp_path / "workspaces")
    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    try:
        loaded = dataset.require("wordcount-001")
    except TaskLoadError as exc:
        pytest.fail(f"sample task missing: {exc}")

    clean = workspaces.prepare(loaded.task, "clean", task_dir=loaded.path, apply_mutation=False)
    mutated = workspaces.prepare(loaded.task, "mutated", task_dir=loaded.path, apply_mutation=True)
    return {
        "clean": clean.path,
        "mutated": mutated.path,
        "hidden_tests": loaded.path / loaded.task.task.hidden_tests,
    }


def test_clean_workspace_passes(sample_workspace: dict[str, Path], tmp_path: Path) -> None:
    engine = EvaluatorEngine(default_registry())
    result = engine.evaluate(
        "pytest_evaluator",
        sample_workspace["clean"],
        out_dir=tmp_path / "out",
        hidden_tests=sample_workspace["hidden_tests"],
        timeout=120,
    )
    assert result.verdict is EvaluationVerdict.PASSED
    assert result.total == 5
    assert result.score == 1.0
    assert result.ok is True
    assert result.raw, "raw output must be kept for re-examination"


def test_mutated_workspace_fails(sample_workspace: dict[str, Path], tmp_path: Path) -> None:
    engine = EvaluatorEngine(default_registry())
    result = engine.evaluate(
        "pytest_evaluator",
        sample_workspace["mutated"],
        out_dir=tmp_path / "out",
        hidden_tests=sample_workspace["hidden_tests"],
        timeout=120,
    )
    assert result.verdict in {EvaluationVerdict.PARTIAL, EvaluationVerdict.FAILED}
    assert result.ok is False
    assert result.failed and result.passed is not None
    assert result.raw


def test_evaluation_never_touches_the_workspace(
    sample_workspace: dict[str, Path], tmp_path: Path
) -> None:
    workspace = sample_workspace["clean"]
    before = _tree_digest(workspace)

    engine = EvaluatorEngine(default_registry())
    engine.evaluate(
        "pytest_evaluator",
        workspace,
        out_dir=tmp_path / "out",
        hidden_tests=sample_workspace["hidden_tests"],
        timeout=120,
    )

    assert _tree_digest(workspace) == before, "evaluation must not modify the workspace"


def test_missing_hidden_tests_is_an_evaluator_error(
    sample_workspace: dict[str, Path], tmp_path: Path
) -> None:
    result = PytestEvaluator().evaluate(
        sample_workspace["clean"],
        out_dir=tmp_path / "out",
        hidden_tests=tmp_path / "does-not-exist",
    )
    assert result.verdict is EvaluationVerdict.EVALUATOR_ERROR
    assert "not found" in result.details["reason"]


def test_regression_is_detected_against_a_baseline() -> None:
    """A previously passing test that now fails is a regression, not a plain failure."""
    from akbench.evaluators.pytest_evaluator import TestCounts, _regressed

    counts = TestCounts(
        total=5,
        passed=3,
        failed=2,
        errors=0,
        skipped=0,
        failing=frozenset({"tests/test_a.py::test_one", "tests/test_a.py::test_two"}),
    )
    baseline = {
        "tests/test_a.py::test_one": "passed",
        "tests/test_a.py::test_two": "passed",
        "tests/test_a.py::test_three": "passed",
    }
    assert _regressed(counts, baseline) == 2
    # without a baseline a regression cannot be claimed, so nothing is invented
    assert _regressed(counts, None) == 0
    assert _regressed(counts, {"tests/test_a.py::test_one": "failed"}) == 0


def test_regression_verdict_from_a_real_run(
    sample_workspace: dict[str, Path], tmp_path: Path
) -> None:
    """The verdict vocabulary distinguishes regression from partial success."""
    from akbench.evaluators.pytest_evaluator import EVALUATOR_ID

    engine = EvaluatorEngine(default_registry())
    baseline = {
        "hidden_tests.test_wordcount_hidden.test_empty_string_has_no_words": "passed",
    }
    result = engine.evaluate(
        EVALUATOR_ID,
        sample_workspace["mutated"],
        out_dir=tmp_path / "out",
        hidden_tests=sample_workspace["hidden_tests"],
        baseline=baseline,
        timeout=120,
    )
    assert result.verdict is EvaluationVerdict.REGRESSION
    assert result.details["regressed_tests"] == 1


def test_command_evaluator_pass_and_fail(sample_workspace: dict[str, Path], tmp_path: Path) -> None:
    from akbench.evaluators.command import CommandEvaluator

    evaluator = CommandEvaluator()
    good = evaluator.evaluate(
        sample_workspace["clean"],
        out_dir=tmp_path / "ok",
        command=[sys.executable, "-c", "print('fine')"],
    )
    assert good.verdict is EvaluationVerdict.PASSED

    bad = evaluator.evaluate(
        sample_workspace["clean"],
        out_dir=tmp_path / "bad",
        command=[sys.executable, "-c", "raise SystemExit(3)"],
    )
    assert bad.verdict is EvaluationVerdict.FAILED
    assert bad.details["exit_code"] == 3


def test_command_evaluator_reports_unrunnable_commands(
    sample_workspace: dict[str, Path], tmp_path: Path
) -> None:
    from akbench.evaluators.command import CommandEvaluator

    result = CommandEvaluator().evaluate(
        sample_workspace["clean"],
        out_dir=tmp_path / "nope",
        command=["/no/such/binary-xyz"],
    )
    assert result.verdict is EvaluationVerdict.EVALUATOR_ERROR
    assert "could not run" in result.details["reason"]


def test_unimplemented_evaluator_is_an_explicit_error(tmp_path: Path) -> None:
    engine = EvaluatorEngine(default_registry())
    from akbench.evaluators.errors import EvaluatorNotFound

    with pytest.raises(EvaluatorNotFound, match="not implemented"):
        engine.evaluate("diff_evaluator", tmp_path, out_dir=tmp_path / "out")


def test_isolation_copies_without_git_admin(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    with evaluation_sandbox(source) as sandbox:
        assert (sandbox / "pkg" / "mod.py").is_file()
        assert not (sandbox / ".git").exists(), ".git must not be copied into the sandbox"


def _tree_digest(root: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(root)).encode())
        h.update(b"\0")
        h.update(path.read_bytes())
    return h.hexdigest()
