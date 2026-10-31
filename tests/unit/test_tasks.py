"""Task Descriptor: identity and the rules that keep a task honest."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from akbench.datasets.task import TaskDescriptor

REPOSITORY = {"source": "datasets/_sources/wordcount", "ref": "HEAD"}


def _body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "category": "bug_fix",
        "difficulty": "easy",
        "repository": dict(REPOSITORY),
        "mutation": {"patch": "mutations/mutation-001.patch", "version": "1.0.0"},
        "evaluator": "pytest_evaluator",
    }
    base.update(overrides)
    return base


def test_task_identity_and_uid() -> None:
    task = TaskDescriptor(id="wordcount-001", version="1.0.0", task=_body())
    assert task.uid == "wordcount-001@1.0.0"
    assert task.category == "bug_fix"
    assert task.difficulty == "easy"
    assert task.evaluator == "pytest_evaluator"
    assert task.requires_mutation() is True


def test_bug_fix_requires_a_mutation() -> None:
    with pytest.raises(ValidationError):
        TaskDescriptor(
            id="t",
            version="1",
            task=_body(category="bug_fix", mutation=None),
        )


def test_new_feature_without_mutation_is_allowed() -> None:
    task = TaskDescriptor(
        id="t",
        version="1",
        task=_body(category="new_feature", mutation=None),
    )
    assert task.requires_mutation() is False


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskDescriptor(
            id="t",
            version="1",
            task=_body(),
            description=None,
            not_a_field=1,
        )


def test_difficulty_is_a_closed_enum() -> None:
    with pytest.raises(ValidationError):
        TaskDescriptor(id="t", version="1", task=_body(difficulty="legendary"))


def test_negative_timeout_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskDescriptor(id="t", version="1", task=_body(timeout_seconds=0))

