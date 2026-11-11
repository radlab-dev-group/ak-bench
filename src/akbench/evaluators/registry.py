"""Evaluator registry (plan section 16).

Adding an evaluator means implementing the contract and registering it here —
the engine, the tasks and the CLI do not change. An evaluator the task asks for
but this installation does not implement raises :class:`EvaluatorNotFound`; it is
never replaced by a stand-in that would produce a meaningless verdict.
"""

from __future__ import annotations

from collections.abc import Iterable

from akbench.evaluators.engine import Evaluator
from akbench.evaluators.errors import EvaluatorNotFound


class EvaluatorRegistry:
    """Evaluator implementations, keyed by id (``id@version`` allowed)."""

    def __init__(self) -> None:
        self._evaluators: dict[tuple[str, str], Evaluator] = {}

    def register(self, evaluator: Evaluator, version: str = "1.0.0") -> None:
        self._evaluators[(evaluator.evaluator_id, version)] = evaluator

    def entries(self) -> list[tuple[str, str]]:
        return sorted(self._evaluators)

    def resolve(self, evaluator_id: str, version: str | None = None) -> Evaluator:
        if version is None:
            versions = {key[1] for key in self._evaluators if key[0] == evaluator_id}
            if not versions:
                raise EvaluatorNotFound(self._message(evaluator_id))
            version = max(versions)
        try:
            return self._evaluators[(evaluator_id, version)]
        except KeyError as exc:
            raise EvaluatorNotFound(self._message(evaluator_id, version)) from exc

    def _message(self, evaluator_id: str, version: str | None = None) -> str:
        implemented = ", ".join(
            f"{name}@{item}" for name, item in sorted(self._evaluators)
        ) or "none"
        suffix = f"@{version}" if version else ""
        return (
            f"evaluator {evaluator_id}{suffix} is not implemented in this installation; "
            f"implemented: {implemented}"
        )

    def __contains__(self, evaluator_id: str) -> bool:
        return any(key[0] == evaluator_id for key in self._evaluators)

    def __len__(self) -> int:
        return len(self._evaluators)

    @staticmethod
    def resolve_reference(reference: str) -> tuple[str, str | None]:
        """Split ``id@version`` into its parts; a bare id resolves to newest."""
        if "@" in reference:
            evaluator_id, version = reference.split("@", 1)
            return evaluator_id, version or None
        return reference, None


def default_registry(extra: Iterable[Evaluator] | None = None) -> EvaluatorRegistry:
    """The evaluators this installation ships with: all five kinds of plan 16.

    ``pytest_evaluator`` is the primary one and the only one that decides a
    task on its own. ``command_evaluator`` is the declared escape hatch;
    ``diff_evaluator`` and ``static_analysis_evaluator`` are supplementary
    signals that never claim a pass they cannot support; ``python_evaluator``
    runs a task's own script under the same isolation and vocabulary. An id
    outside these five is still an explicit :class:`EvaluatorNotFound` — never
    a silent approximation by a lookalike.
    """
    from akbench.evaluators.command import CommandEvaluator
    from akbench.evaluators.diff import DiffEvaluator
    from akbench.evaluators.pytest_evaluator import PytestEvaluator
    from akbench.evaluators.python_evaluator import PythonEvaluator
    from akbench.evaluators.static_analysis import StaticAnalysisEvaluator

    registry = EvaluatorRegistry()
    registry.register(PytestEvaluator())
    registry.register(CommandEvaluator())
    registry.register(DiffEvaluator())
    registry.register(StaticAnalysisEvaluator())
    registry.register(PythonEvaluator())
    for evaluator in extra or ():
        registry.register(evaluator)
    return registry
