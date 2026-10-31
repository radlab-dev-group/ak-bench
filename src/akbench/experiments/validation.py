"""Validation findings for an experiment (plan section 12.1).

An error blocks the experiment: a plan built on an agent that cannot do what the
experiment assumes measures something else. A warning does not block, but it
stays in the plan and in the report, so a reader sees what was not verified
rather than assuming it was fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    """One finding, with a stable code so tests and reports can name it."""

    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.ERROR
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.context:
            payload["context"] = dict(self.context)
        return payload


@dataclass
class ValidationReport:
    """All findings of one validation pass."""

    issues: list[ValidationIssue] = field(default_factory=list)

    def error(self, code: str, message: str, **context: Any) -> None:
        self.issues.append(
            ValidationIssue(code, message, IssueSeverity.ERROR, dict(context))
        )

    def warn(self, code: str, message: str, **context: Any) -> None:
        self.issues.append(
            ValidationIssue(code, message, IssueSeverity.WARNING, dict(context))
        )

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is IssueSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is IssueSeverity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: ValidationReport) -> None:
        self.issues.extend(other.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "issues": [issue.as_dict() for issue in self.issues],
        }
