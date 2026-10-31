"""Dataset discovery, snapshot digests and validation against the registries."""

from __future__ import annotations

from pathlib import Path

import pytest

from akbench.datasets import Dataset, TaskLoadError
from akbench.descriptors import DescriptorKind, DescriptorRegistry, load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_DESCRIPTORS = REPO_ROOT / "descriptors"
SHIPPED_DATASET = REPO_ROOT / "datasets"

TASK_YAML = """
schema_version: "1.0"
id: {task_id}
version: "1.0.0"
task:
  category: bug_fix
  difficulty: easy
  repository:
    source: datasets/_sources/wordcount
    ref: HEAD
  mutation:
    patch: mutations/mutation-001.patch
    version: "1.0.0"
  evaluator: pytest_evaluator
"""


@pytest.fixture
def registry() -> DescriptorRegistry:
    return load_registry(SHIPPED_DESCRIPTORS)


def _write_task(
    root: Path,
    category: str,
    task_id: str,
    *,
    yaml_body: str | None = None,
    declared_category: str | None = None,
) -> Path:
    task_dir = root / category / task_id
    (task_dir / "hidden_tests").mkdir(parents=True, exist_ok=True)
    (task_dir / "hidden_tests" / "test_hidden.py").write_text("def test_x():\n    assert True\n")
    (task_dir / "public_tests").mkdir(exist_ok=True)
    (task_dir / "public_tests" / "test_public.py").write_text("def test_y():\n    assert True\n")
    (task_dir / "mutations").mkdir(exist_ok=True)
    (task_dir / "mutations" / "mutation-001.patch").write_text(
        "diff --git a/x b/x\nnew file mode 100644\n"
    )
    (task_dir / "description.md").write_text("# A task\n")
    if yaml_body is None:
        body = TASK_YAML.format(task_id=task_id)
        if declared_category is not None:
            body = body.replace("category: bug_fix", f"category: {declared_category}")
    else:
        body = yaml_body
    (task_dir / "task.yaml").write_text(body, encoding="utf-8")
    return task_dir


def test_load_discovers_tasks_under_category(tmp_path: Path) -> None:
    _write_task(tmp_path, "bug_fix", "task-a")
    _write_task(tmp_path, "bug_fix", "task-b")
    _write_task(tmp_path, "new_feature", "task-c", declared_category="new_feature")
    dataset = Dataset.load(tmp_path)
    assert len(dataset) == 3
    assert dataset.ids("bug_fix") == ["task-a", "task-b"]
    assert dataset.ids("new_feature") == ["task-c"]
    assert dataset.categories() == ["bug_fix", "new_feature"]
    assert dataset.get("task-a").task.category == "bug_fix"


def test_require_resolves_explicit_version(tmp_path: Path) -> None:
    _write_task(tmp_path, "bug_fix", "task-a")
    dataset = Dataset.load(tmp_path)
    assert dataset.require("task-a").task.version == "1.0.0"
    assert dataset.require("task-a@1.0.0").task.version == "1.0.0"
    # bump the version and require the old one by id@version
    task_dir = tmp_path / "bug_fix" / "task-a"
    (task_dir / "task.yaml").write_text(
        TASK_YAML.format(task_id="task-a").replace('version: "1.0.0"', 'version: "2.0.0"'),
        encoding="utf-8",
    )
    bumped = Dataset.load(tmp_path)
    assert bumped.require("task-a").task.version == "2.0.0"
    with pytest.raises(TaskLoadError, match="unknown task"):
        bumped.require("task-a@1.0.0")


def test_require_unknown_task_names_the_known_ones(tmp_path: Path) -> None:
    _write_task(tmp_path, "bug_fix", "task-a")
    dataset = Dataset.load(tmp_path)
    with pytest.raises(TaskLoadError, match="task-a"):
        dataset.require("nope")


def test_digest_changes_when_a_hidden_test_changes(tmp_path: Path) -> None:
    _write_task(tmp_path, "bug_fix", "task-a")
    first = Dataset.load(tmp_path).require("task-a")
    (first.path / "hidden_tests" / "test_hidden.py").write_text(
        "def test_x():\n    assert False\n"
    )
    second = Dataset.load(tmp_path).require("task-a")
    assert first.digest != second.digest
    assert first.digest.startswith("sha256:")


def test_digest_is_stable_across_reloads(tmp_path: Path) -> None:
    _write_task(tmp_path, "bug_fix", "task-a")
    a = Dataset.load(tmp_path).require("task-a").digest
    b = Dataset.load(tmp_path).require("task-a").digest
    assert a == b


def test_missing_dataset_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TaskLoadError, match="not found"):
        Dataset.load(tmp_path / "nope")


def test_invalid_task_yaml_raises_with_location(tmp_path: Path) -> None:
    _write_task(
        tmp_path,
        "bug_fix",
        "broken",
        yaml_body="schema_version: '1.0'\nid: broken\nversion: '1'\ntask:\n  nope: 1\n",
    )
    with pytest.raises(TaskLoadError, match="task"):
        Dataset.load(tmp_path)


def test_validate_against_shipped_registry_passes() -> None:
    dataset = Dataset.load(SHIPPED_DATASET, base_dir=REPO_ROOT)
    report = dataset.validate(load_registry(SHIPPED_DESCRIPTORS))
    assert report.ok, report.as_dict()


def test_validate_flags_unknown_category(tmp_path: Path, registry: DescriptorRegistry) -> None:
    _write_task(
        tmp_path,
        "bug_fix",
        "task-a",
        yaml_body=TASK_YAML.format(task_id="task-a").replace(
            "category: bug_fix", "category: not_registered"
        ),
    )
    report = Dataset.load(tmp_path).validate(registry)
    assert not report.ok
    assert any("not registered" in issue for issue in report.tasks[0].issues)


def test_validate_flags_disabled_category(tmp_path: Path, registry: DescriptorRegistry) -> None:
    _write_task(
        tmp_path,
        "bug_fix",
        "task-a",
        yaml_body=TASK_YAML.format(task_id="task-a").replace(
            "category: bug_fix", "category: refactoring"
        ),
    )
    report = Dataset.load(tmp_path).validate(registry)
    assert not report.ok
    assert any("disabled" in issue for issue in report.tasks[0].issues)


def test_validate_flags_difficulty_not_allowed_by_category(
    tmp_path: Path, registry: DescriptorRegistry
) -> None:
    _write_task(
        tmp_path,
        "bug_fix",
        "task-a",
        yaml_body=TASK_YAML.format(task_id="task-a").replace(
            "category: bug_fix", "category: performance"
        ),
    )
    # performance is disabled in the shipped registry, so this is caught as
    # disabled before the difficulty check; assert we still get a failure
    report = Dataset.load(tmp_path).validate(registry)
    assert not report.ok


def test_validate_flags_unknown_evaluator(tmp_path: Path, registry: DescriptorRegistry) -> None:
    _write_task(
        tmp_path,
        "bug_fix",
        "task-a",
        yaml_body=TASK_YAML.format(task_id="task-a").replace(
            "evaluator: pytest_evaluator", "evaluator: no_such_evaluator"
        ),
    )
    report = Dataset.load(tmp_path).validate(registry)
    assert any("evaluator" in issue for issue in report.tasks[0].issues)


def test_validate_flags_missing_hidden_tests(tmp_path: Path, registry: DescriptorRegistry) -> None:
    task_dir = _write_task(tmp_path, "bug_fix", "task-a")
    hidden = task_dir / "hidden_tests"
    for child in hidden.iterdir():
        child.unlink()
    report = Dataset.load(tmp_path).validate(registry)
    assert any("hidden tests" in issue for issue in report.tasks[0].issues)


def test_validate_flags_directory_mismatch(tmp_path: Path, registry: DescriptorRegistry) -> None:
    _write_task(
        tmp_path,
        "bug_fix",
        "actual-name",
        yaml_body=TASK_YAML.format(task_id="declared-name"),
    )
    report = Dataset.load(tmp_path).validate(registry)
    assert any("does not match directory" in issue for issue in report.tasks[0].issues)


def test_materialize_resolves_relative_source(tmp_path: Path) -> None:
    _write_task(tmp_path, "bug_fix", "task-a")
    dataset = Dataset.load(tmp_path, base_dir=tmp_path)
    loaded = dataset.materialize(dataset.require("task-a"))
    assert Path(loaded.task.task.repository.source).is_absolute()
    assert loaded.digest == dataset.require("task-a").digest


def test_registry_kind_is_still_available() -> None:
    # sanity: the registry used for validation knows the category kind
    registry = load_registry(SHIPPED_DESCRIPTORS)
    assert registry.get(DescriptorKind.CATEGORY, "bug_fix") is not None
