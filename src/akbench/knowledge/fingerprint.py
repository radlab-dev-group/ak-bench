"""Fingerprints that prove two arms differ in knowledge and nothing else.

Plan section 17 requires replay and fresh control to share the repository
snapshot, task version, tests, evaluator, agent, parameters and limits. That
is not a convention to remember but a comparison to run: each arm carries a
fingerprint of the facts that must be equal, and the planner refuses a
difference by naming the key that differs.

A fingerprint is a digest over canonical JSON, so it survives a round-trip
through YAML or the database, and it changes when — and only when — one of the
pinned facts changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from akbench.descriptors.registry import canonical_json, compute_digest

#: The facts every arm of a memory experiment must agree on.
MEMORY_INVARIANTS: tuple[str, ...] = (
    "repository",
    "commit",
    "task",
    "task_digest",
    "evaluator",
    "agent",
    "agent_config",
    "model",
    "limits",
    "sandbox_image",
)


@dataclass(frozen=True)
class Fingerprint:
    """A digest plus the facts behind it.

    Keeping the facts alongside the digest is what makes a mismatch readable:
    a hash difference alone says "not the same" and nothing else.
    """

    digest: str
    facts: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"digest": self.digest, "facts": dict(self.facts)}


def fingerprint(facts: dict[str, Any]) -> Fingerprint:
    """Digest a mapping canonically, dropping keys with no value.

    A key whose value is ``None`` is treated as "not stated" and left out, so
    an arm that knows a fact and one that does not are compared on the facts
    both of them state.
    """
    stated = {key: value for key, value in facts.items() if value is not None}
    return Fingerprint(digest=compute_digest(stated), facts=stated)


def invariant_fingerprint(
    facts: dict[str, Any],
    keys: tuple[str, ...] = MEMORY_INVARIANTS,
) -> Fingerprint:
    """Digest only the invariants, so an unrelated difference cannot hide one."""
    selected = {key: facts.get(key) for key in keys if key in facts}
    return fingerprint(selected)


def invariant_differences(
    left: dict[str, Any],
    right: dict[str, Any],
    keys: tuple[str, ...] = MEMORY_INVARIANTS,
) -> list[str]:
    """Keys whose value differs, or which one side states and the other does not.

    Both directions count: a fact present on one side only is a difference,
    because "unknown" is not the same condition as "known and equal".
    """
    differences: list[str] = []
    for key in keys:
        left_value, right_value = left.get(key), right.get(key)
        if _normalize(left_value) != _normalize(right_value):
            differences.append(key)
    return differences


def _normalize(value: Any) -> Any:
    """Make equivalent structures compare equal regardless of key order."""
    if isinstance(value, dict):
        return canonical_json(value)
    if isinstance(value, (list, tuple)):
        return canonical_json(list(value))
    if isinstance(value, bool):
        return value
    return value
