#!/usr/bin/env python
"""Regenerate ``datasets/README.md`` from the task descriptors.

The README is the human index of the dataset: one row per task and the
``task_ids`` lists an experiment YAML pastes in. Both were maintained by hand,
and both drifted: the index listed 77 of 99 tasks, and one multiline list had
lost a newline, producing the entry ``tidewater-snapshot-002  - timetable-overlap-001``
— a YAML document that parses and names a task that does not exist.

This script makes the file a projection of the descriptors instead. The prose
above the table and the notes below the lists are kept; the table and every
``task_ids`` block are rewritten. Run it with ``--check`` in CI to fail on a
dataset that has grown without the index.

    python scripts/update_dataset_readme.py          # rewrite
    python scripts/update_dataset_readme.py --check  # exit 1 when stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS = REPO_ROOT / "datasets"
README = DATASETS / "README.md"
CODES = DATASETS / "task-codes.json"
TASK_FILE = "task.yaml"

#: The category order an experiment author expects: the two original families
#: first, then the roadmap's, then the ones added alongside them.
CATEGORY_ORDER = [
    "bug_fix",
    "new_feature",
    "debugging",
    "security",
    "refactoring",
    "testing",
    "code_review",
    "performance",
    "architecture",
]

#: The prefix a category's codes use. A code is published when its task is: it
#: is what an experiment, a report and a conversation about the dataset name.
#: ``datasets/task-codes.json`` pins every code ever issued, and this script
#: only ever appends to it — a task keeps its code, and a new task takes the
#: next free number in its category.
CATEGORY_CODES = {
    "bug_fix": "BF",
    "new_feature": "NF",
    "debugging": "DB",
    "security": "SEC",
    "refactoring": "RF",
    "testing": "TST",
    "code_review": "CR",
    "performance": "PERF",
    "architecture": "ARCH",
}

#: The heading each category gets in the per-category sections.
CATEGORY_TITLES = {
    "bug_fix": "Bugfix tasks",
    "new_feature": "New feature tasks",
    "debugging": "Debugging tasks",
    "security": "Security tasks",
    "refactoring": "Refactoring tasks",
    "testing": "Testing tasks",
    "code_review": "Code review tasks",
    "performance": "Performance tasks",
    "architecture": "Architecture tasks",
}

#: The columns of the ``## All tasks`` table, in the order a reader wants them.
#: The widths are measured from the rows, so the file stays aligned as tasks are
#: added and a diff shows one row rather than the whole table.
COLUMNS = (
    "ID",
    "Task",
    "Type",
    "Description",
    "Difficulty",
    "Created by",
    "When added",
)

INTRO = "## All tasks in **AK-Benchmark**\n\n"

AFTER_TABLE = """
`Difficulty` is the task descriptor's own `task.difficulty`
(`src/akbench/datasets/task.py`: `easy` | `medium` | `hard` | `expert`), so the
table and `akbench dataset list` can never disagree. Difficulty is a property of
the task, not of the timeout beside it: an `expert` task is one whose complete
solution a strong model does not reach in one pass, whatever the clock allows.
`expert` tasks are the ones an experiment plans when it wants to separate agents
that can hold a large invariant in mind from agents that can only patch locally.
The `task_ids` lists below are a convenience for the experiment YAML; they do
not repeat the difficulty, which the table above and the descriptors are the
source of.

This file is generated from the descriptors by
`scripts/update_dataset_readme.py`; `--check` fails when it is stale, so a task
cannot join the dataset without appearing here.
"""


def load_tasks() -> list[dict]:
    """Every task descriptor, in the order the README presents them."""
    tasks: list[dict] = []
    for path in sorted(DATASETS.glob(f"*/*/{TASK_FILE}")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        body = document["task"]
        tasks.append(
            {
                "id": document["id"],
                "category": body["category"],
                "difficulty": body["difficulty"],
                "authors": list(document.get("authors") or []),
                "created_at": str(document.get("created_at") or ""),
                "link": f"./{path.parent.relative_to(DATASETS).as_posix()}/description.md",
            }
        )
    assign_codes(tasks)
    order = {name: index for index, name in enumerate(CATEGORY_ORDER)}
    tasks.sort(key=lambda task: (order.get(task["category"], 99), task["id"]))
    return tasks


def read_codes() -> dict[str, str]:
    if not CODES.is_file():
        return {}
    return json.loads(CODES.read_text(encoding="utf-8"))


def assign_codes(tasks: list[dict]) -> dict[str, str]:
    """Give every task its published code, issuing one for a task that has none.

    Returns the mapping to persist; nothing is written here, so that ``--check``
    and the tests can render without touching the working tree.
    """
    published = read_codes()
    used = set(published.values())
    issued = dict(published)
    for task in tasks:
        code = issued.get(task["id"])
        if code is None:
            prefix = CATEGORY_CODES.get(task["category"], "TASK")
            number = 1
            while f"{prefix}_{number:03d}" in used:
                number += 1
            code = f"{prefix}_{number:03d}"
            issued[task["id"]] = code
            used.add(code)
        task["code"] = code
    return issued


def codes_of(tasks: list[dict]) -> dict[str, str]:
    """The code each task carries, as the file that pins them stores it."""
    return dict(sorted((task["id"], task["code"]) for task in tasks))


def author_label(task: dict) -> str:
    """How the table names the author, exactly as the descriptor writes it."""
    if not task["authors"]:
        return "—"
    return ", ".join(task["authors"])


def when(task: dict) -> str:
    """``YYYY-MM-DD HH:MM`` in the descriptor's own offset, or an em dash."""
    stamp = task["created_at"]
    match = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", stamp)
    return f"{match.group(1)} {match.group(2)}" if match else "—"


def render_table(tasks: list[dict]) -> str:
    """The table of every task, aligned to the widest cell in each column."""
    body = [
        [
            f"`{task['code']}`",
            f"`{task['id']}`",
            f"`{task['category']}`",
            f"[READ]({task['link']})",
            f"`{task['difficulty']}`",
            author_label(task),
            f"`{when(task)}`",
        ]
        for task in tasks
    ]
    widths = [
        max([len(COLUMNS[index])] + [len(row[index]) for row in body])
        for index in range(len(COLUMNS))
    ]

    def line(cells: list[str]) -> str:
        padded = (cell.ljust(width) for cell, width in zip(cells, widths, strict=True))
        return "| " + " | ".join(padded) + " |"

    rule = line(["-" * width for width in widths])
    rows = [line(list(COLUMNS)), rule, *(line(row) for row in body)]
    return "\n".join(rows) + "\n"


def yaml_block(tasks: list[dict]) -> str:
    """A single-line and a multiline ``task_ids`` block, both valid YAML."""
    ids = [task["id"] for task in tasks]
    if not ids:
        return "No tasks.\n"
    single = "```yaml\ntask_ids: [ " + ", ".join(ids) + " ]\n```\n"
    multiline = "```yaml\ntask_ids:\n" + "".join(f"  - {i}\n" for i in ids) + "```\n"
    return f"Single line\n{single}\nMultiline\n{multiline}\n"


def render_lists(tasks: list[dict]) -> str:
    """The whole ``task_ids`` section: all tasks, then one section per category."""
    parts = ["Below is the list of the all available tasks without a split to task type\n\n"]
    parts.append(yaml_block(tasks))
    for category in CATEGORY_ORDER:
        subset = [task for task in tasks if task["category"] == category]
        if not subset:
            continue
        parts.append(f"---\n\n### {CATEGORY_TITLES[category]}\n\n")
        parts.append(f"**All `{category}` tasks**\n\n")
        parts.append(yaml_block(subset))
    return "".join(parts)


def render(tasks: list[dict]) -> str:
    return INTRO + render_table(tasks) + AFTER_TABLE + "\n\n" + render_lists(tasks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when stale instead of writing")
    arguments = parser.parse_args()

    tasks = load_tasks()
    wanted = render(tasks)
    current = README.read_text(encoding="utf-8") if README.is_file() else ""
    codes = codes_of(tasks)
    new_codes = codes != read_codes()

    if arguments.check:
        stale = []
        if current != wanted:
            stale.append(f"{README.relative_to(REPO_ROOT)} is stale")
        if new_codes:
            stale.append(f"{CODES.relative_to(REPO_ROOT)} has no code for every task")
        if stale:
            print(f"{'; '.join(stale)}: run {Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"datasets/README.md names all {len(tasks)} tasks")
        return 0

    if new_codes:
        CODES.write_text(json.dumps(codes, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CODES.relative_to(REPO_ROOT)}: {len(codes)} codes")
    README.write_text(wanted, encoding="utf-8")
    print(f"wrote {README.relative_to(REPO_ROOT)}: {len(tasks)} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
