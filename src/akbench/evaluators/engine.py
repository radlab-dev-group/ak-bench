"""The evaluator engine: outcome vocabulary and the shared contract.

The engine does not know how to run pytest — an :class:`Evaluator` does. What
the engine owns is the vocabulary of outcomes and the guarantee that the two
kinds of failure stay separated:

- an **agent failure** is the thing being measured (the hidden tests failed);
- an **evaluator error** is a problem with the measurement itself (the tests
  could not be collected, the interpreter is missing, the runner timed out).

Plan section 16 lists what must be distinguishable: full success, partial
success, failure, regression, timeout, evaluator error, infrastructure error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from akbench.evaluators.registry import EvaluatorRegistry


class EvaluationVerdict(StrEnum):
    """The outcome of one evaluation, distinct from the agent's own status."""

    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    REGRESSION = "regression"
    TIMEOUT = "timeout"
    EVALUATOR_ERROR = "evaluator_error"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


@dataclass(frozen=True)
class EvaluationResult:
    """What the evaluator decided, plus everything needed to re-examine it.

    ``raw`` keeps the native report (or command output) verbatim: a pass/fail
    claim must always be re-examinable, which is why raw output belongs to the
    model rather than being an optional extra.
    """

    evaluator_id: str
    evaluator_version: str
    verdict: EvaluationVerdict
    score: float | None = None
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    total: int | None = None
    duration_seconds: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    raw: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True only for a full pass; a partial result is not a success."""
        return self.verdict is EvaluationVerdict.PASSED

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "verdict": self.verdict.value,
            "score": self.score,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "total": self.total,
            "duration_seconds": self.duration_seconds,
            "details": dict(self.details),
            "artifacts": dict(self.artifacts),
            "raw": self.raw,
        }


@runtime_checkable
class Evaluator(Protocol):
    """What every evaluator implements.

    ``evaluate`` receives the produced workspace and an output directory for raw
    reports. An evaluator that cannot run must return an ``EVALUATOR_ERROR``
    result with the reason in ``details`` rather than raise: the engine has to
    be able to report *why* the measurement failed.
    """

    evaluator_id: str
    kind: str

    def evaluate(
        self,
        workspace: Path,
        *,
        out_dir: Path,
        timeout: float | None = None,
        **inputs: Any,
    ) -> EvaluationResult: ...


class EvaluatorEngine:
    """Resolves an evaluator by reference and runs it against a workspace.

    Deliberately thin: it splits ``id@version``, resolves through the registry,
    prepares the output directory and returns whatever the evaluator reports.
    Adding an evaluator never changes this class.
    """

    def __init__(self, registry: EvaluatorRegistry) -> None:
        self.registry = registry

    def evaluate(
        self,
        evaluator_reference: str,
        workspace: Path,
        *,
        out_dir: Path,
        timeout: float | None = None,
        **inputs: Any,
    ) -> EvaluationResult:
        from akbench.evaluators.registry import EvaluatorRegistry

        evaluator_id, version = EvaluatorRegistry.resolve_reference(evaluator_reference)
        evaluator = self.registry.resolve(evaluator_id, version)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        return evaluator.evaluate(
            Path(workspace), out_dir=Path(out_dir), timeout=timeout, **inputs
        )

    def implemented(self) -> list[tuple[str, str]]:
        return self.registry.entries()
