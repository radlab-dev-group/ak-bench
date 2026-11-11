"""Every complete YAML example in the documentation is validated.

Documentation that lies is worse than no documentation, and the examples in
`docs/` are the part a reader copies. This file extracts each fenced ``yaml``
block from the docs and runs it through the same loader the platform uses, so a
field renamed in code cannot stay documented.

A block is validated when it is a complete descriptor document — the
``schema_version``/``id``/``version`` header plus exactly one kind body. A
block that shows a fragment of a larger file (one section, an illustrative
pair of keys) is marked `````yaml fragment````` and skipped, because a fragment
is not a document and pretending otherwise would force the docs into quoting
whole files to illustrate one line. The count of validated blocks is asserted
so the suite cannot pass by validating nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from akbench.datasets.task import TaskDescriptor
from akbench.descriptors import (
    AgentDescriptor,
    CategoryDescriptor,
    DimensionDescriptor,
    EnvironmentDescriptor,
    EvaluatorDescriptor,
    MetricDescriptor,
    ModelDescriptor,
    PluginDescriptor,
    RuntimeDescriptor,
)
from akbench.experiments.descriptor import ExperimentDescriptor

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"

#: The fence info string that marks a deliberate fragment.
FRAGMENT = "fragment"

_BLOCK = re.compile(r"^```yaml(?P<info>[^\n]*)\n(?P<body>.*?)^```", re.DOTALL | re.MULTILINE)

#: The kind body that names which model validates a document. A block with none
#: of these is not a descriptor document, and one with several is ambiguous.
BODIES: dict[str, type[BaseModel]] = {
    "task": TaskDescriptor,
    "experiment": ExperimentDescriptor,
    "agent": AgentDescriptor,
    "runtime": RuntimeDescriptor,
    "plugin": PluginDescriptor,
    "model": ModelDescriptor,
    "category": CategoryDescriptor,
    "evaluator": EvaluatorDescriptor,
    "dimension": DimensionDescriptor,
    "metric": MetricDescriptor,
    "environment": EnvironmentDescriptor,
}

HEADER = ("schema_version", "id", "version")


def _blocks(path: Path) -> list[tuple[int, str, object]]:
    """The ``(line, info, document)`` of each fenced ``yaml`` block in a file."""
    text = path.read_text(encoding="utf-8")
    found: list[tuple[int, str, object]] = []
    for match in _BLOCK.finditer(text):
        info = match.group("info").strip()
        line = text.count("\n", 0, match.start()) + 1
        try:
            document = yaml.safe_load(match.group("body"))
        except yaml.YAMLError as exc:  # a block that is not valid YAML at all
            pytest.fail(f"{path.relative_to(REPO_ROOT)}:{line}: block is not valid YAML: {exc}")
        found.append((line, info, document))
    return found


def _candidate(path: Path, line: int, info: str, document: object) -> str | None:
    """Why this block should be validated, or ``None`` when it should be skipped."""
    if FRAGMENT in info.lower():
        return None
    if not isinstance(document, dict):
        pytest.fail(
            f"{path.relative_to(REPO_ROOT)}:{line}: a documented descriptor block must be a "
            "mapping; mark a list or scalar block as ```yaml fragment```"
        )
    if not all(name in document for name in HEADER):
        return None  # a section quoted from a larger file, not a document
    return f"{path.relative_to(REPO_ROOT)}:{line}"


def _examples() -> list[tuple[str, type[BaseModel], dict]]:
    collected: list[tuple[str, type[BaseModel], dict]] = []
    for path in sorted(DOCS.glob("*.md")):
        for line, info, document in _blocks(path):
            where = _candidate(path, line, info, document)
            if where is None:
                continue
            kinds = [name for name in document if name in BODIES]
            if not kinds:
                pytest.fail(
                    f"{where}: a complete descriptor block must carry exactly one kind body "
                    f"of {sorted(BODIES)}; mark it ```yaml fragment``` if it is an example "
                    "of something else"
                )
            if len(kinds) > 1:
                pytest.fail(f"{where}: descriptor block carries more than one kind body: {kinds}")
            collected.append((where, BODIES[kinds[0]], document))
    return collected


def _ids(entry: tuple[str, type[BaseModel], dict]) -> str:
    where, _, document = entry
    return f"{where}-{document.get('id', '?')}"


EXAMPLES = _examples()


def test_the_docs_hold_examples_to_validate() -> None:
    """A guard against the guard checking nothing."""
    assert EXAMPLES, f"no descriptor examples found under {DOCS}"
    validated = {document["id"] for _, _, document in EXAMPLES}
    assert len(validated) >= 5, f"only {sorted(validated)} validate, too few to mean anything"


@pytest.mark.parametrize("entry", EXAMPLES, ids=_ids)
def test_a_documented_example_validates(entry: tuple[str, type[BaseModel], dict]) -> None:
    where, model, document = entry
    try:
        model.model_validate(document)
    except ValidationError as exc:  # pragma: no cover - the failure is the point
        issues = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or '<root>'}: {issue['msg']}"
            for issue in exc.errors()
        )
        pytest.fail(f"{where}: {model.__name__} rejects the documented example: {issues}")


def test_the_documented_kinds_are_covered() -> None:
    """Each kind the docs are meant to teach has at least one validated example."""
    covered = {model.__name__ for _, model, _ in EXAMPLES}
    assert covered >= {
        TaskDescriptor.__name__,
        ExperimentDescriptor.__name__,
        CategoryDescriptor.__name__,
        DimensionDescriptor.__name__,
    }, f"the docs validate {sorted(covered)}; these kinds teach their format from an example"
