"""Dataset integrity guards: a reference is only as good as the file it names.

A task that declares mutation parts promises they exist. When a `.gitignore`
pattern hid `mutations/parts/` from git, `parts.json` still named them, the
planner still accepted the task, and only a full mutation run found out —
which is exactly the class of failure this test keeps out of a checkout.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "datasets"

PARTS_FILES = sorted(DATASETS.glob("*/*/mutations/parts.json"))


def _tracked(path: Path) -> bool:
    """True when git has a file at this exact path (skipped outside a checkout)."""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_the_dataset_tree_is_where_the_parts_glob_expects_it() -> None:
    assert DATASETS.is_dir(), f"no datasets directory under {ROOT}"
    assert PARTS_FILES, "no task ships mutations/parts.json, which no longer matches the suite"


@pytest.mark.parametrize(
    "parts_file", PARTS_FILES, ids=lambda path: path.parents[2].name
)
def test_every_declared_part_exists_and_is_committed(parts_file: Path) -> None:
    if (ROOT / ".git").is_dir() and not _tracked(parts_file):
        pytest.skip(f"{parts_file} is not tracked by git")
    entries = json.loads(parts_file.read_text(encoding="utf-8"))
    assert isinstance(entries, list) and entries, f"{parts_file} must list at least one part"
    mutations = parts_file.parent
    for entry in entries:
        patch = mutations / entry["patch"]
        assert patch.is_file(), f"{parts_file} references {patch}, which does not exist"
        assert entry.get("witness"), f"{parts_file} has a part without a witness test"
        if (ROOT / ".git").is_dir():
            assert _tracked(patch), f"{patch} is referenced but not committed to git"
