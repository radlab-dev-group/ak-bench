"""The dataset index is a projection of the descriptors, and it says so.

``datasets/README.md`` used to be maintained by hand, and drifted: it listed 77
of 99 tasks, and one of its multiline ``task_ids`` blocks had lost a newline, so
the entry ``tidewater-snapshot-002  - timetable-overlap-001`` parsed as a task
id that does not exist. An experiment that pasted that list benchmarked a
smaller dataset than it claimed, silently.

These tests pin the file to `scripts/update_dataset_readme.py`, which reads the
descriptors: a task that joins the dataset without appearing in the index fails
here, and so does a hand edit that the script would undo.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS = REPO_ROOT / "datasets"
README = DATASETS / "README.md"


def _script_module():
    """Import scripts/update_dataset_readme.py without making scripts a package."""
    path = REPO_ROOT / "scripts" / "update_dataset_readme.py"
    spec = importlib.util.spec_from_file_location("update_dataset_readme", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tasks() -> list[dict]:
    return _script_module().load_tasks()


def test_the_index_is_current(tasks: list[dict]) -> None:
    """The README is exactly what the generator would write today."""
    module = _script_module()
    assert README.read_text(encoding="utf-8") == module.render(tasks), (
        "datasets/README.md is stale: run scripts/update_dataset_readme.py"
    )


def test_every_task_on_disk_is_in_the_table() -> None:
    text = README.read_text(encoding="utf-8")
    listed = set(re.findall(r"^\|\s*`[A-Z]+_\d+`\s*\|\s*`([^`]+)`", text, re.M))
    on_disk = {path.parent.name for path in DATASETS.glob("*/*/task.yaml")}
    assert listed == on_disk, sorted(on_disk ^ listed)


def test_every_task_ids_block_is_valid_yaml_and_names_real_tasks() -> None:
    text = README.read_text(encoding="utf-8")
    on_disk = {path.parent.name for path in DATASETS.glob("*/*/task.yaml")}
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.S)
    assert blocks, "the README carries no task_ids block at all"
    for block in blocks:
        document = yaml.safe_load(block)
        assert isinstance(document, dict) and "task_ids" in document, block[:80]
        ids = document["task_ids"]
        assert isinstance(ids, list) and ids, block[:80]
        unknown = [task_id for task_id in ids if task_id not in on_disk]
        assert not unknown, f"block names tasks that do not exist: {unknown}"
        assert len(set(ids)) == len(ids), f"block repeats a task: {block[:80]}"


def test_the_list_of_all_tasks_names_every_task() -> None:
    """The first block is the copy-paste list of the whole dataset."""
    text = README.read_text(encoding="utf-8")
    first = re.findall(r"```yaml\n(.*?)```", text, re.S)[0]
    ids = set(yaml.safe_load(first)["task_ids"])
    on_disk = {path.parent.name for path in DATASETS.glob("*/*/task.yaml")}
    assert ids == on_disk, sorted(on_disk ^ ids)


def test_a_published_code_never_changes_hands() -> None:
    """``task-codes.json`` is append-only: a code names one task, forever."""
    codes = yaml.safe_load((DATASETS / "task-codes.json").read_text(encoding="utf-8"))
    assert len(set(codes.values())) == len(codes), "two tasks share a code"
    on_disk = {path.parent.name for path in DATASETS.glob("*/*/task.yaml")}
    assert set(codes) <= on_disk, f"codes for tasks that no longer exist: {set(codes) - on_disk}"


def test_rendering_writes_nothing() -> None:
    """``--check`` has to be safe to run in CI, and the tests run the same code.

    ``render`` used to issue missing codes as a side effect, so a test that asked
    "is the index current?" could quietly change the file it was checking.
    """
    codes_before = (DATASETS / "task-codes.json").read_text(encoding="utf-8")
    readme_before = README.read_text(encoding="utf-8")
    module = _script_module()

    module.render(module.load_tasks())

    assert (DATASETS / "task-codes.json").read_text(encoding="utf-8") == codes_before
    assert README.read_text(encoding="utf-8") == readme_before
