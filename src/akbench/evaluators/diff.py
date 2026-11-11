"""The diff evaluator (plan section 16, supplementary).

Compares what the agent actually changed with a reference patch and reports the
overlap as a score. It is deliberately *not* a success criterion: a diff can
look right and be wrong, so the verdict is `partial` when there is overlap and
`failed` when there is none — it never returns `passed`, because only tests can
prove correctness (the descriptor says the same).

Both sides are counted in the same units, which is what makes the score mean
something: a unified diff names the base-side line numbers it touches, so the
produced change (`git diff HEAD` plus the files the agent added) and the
reference (read from its patch header) are coordinates in the same pristine
base, compared line for line.

Why this evaluator reads the workspace instead of copying it: a diff is a
relation between a working tree and the commit it was prepared from, and the
evaluation sandbox deliberately drops `.git` (plan 8.6, 23) — copying would
destroy exactly the relation being measured. Nothing here writes: `git diff`
and `git status` open the object store read-only and leave the tree byte for
byte as it was, so the guarantee the sandbox exists to provide still holds.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from akbench.evaluators.engine import EvaluationResult, EvaluationVerdict

EVALUATOR_ID = "diff_evaluator"
EVALUATOR_VERSION = "1.0.0"

_HUNK = re.compile(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")

#: A hunk with no base-side line numbers at all; nothing can match it, so it is
#: skipped rather than guessed at.
_HUNK_WITHOUT_BASE = re.compile(r"^@@ -\d+ \+\d+ @@$")

#: A line number no real file has: it marks a file that did not exist in the
#: base, which is how a created file is recorded on both sides.
_CREATED = 0


def changed_lines(text: str) -> dict[str, set[int]]:
    """Base-side line numbers a unified diff removes or replaces, per file.

    `git diff` output and a patch file share this shape, so one reader serves
    both sides of the comparison. A file created by the patch is recorded under
    the sentinel line :data:`_CREATED`, so a produced file with no base matches
    a reference that also creates it.
    """
    lines: dict[str, set[int]] = {}
    current: str | None = None
    cursor: int | None = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = line.split(" b/", 1)[1]
            lines.setdefault(current, set())
        elif line.startswith("@@"):
            if _HUNK_WITHOUT_BASE.match(line):
                cursor = None
                continue
            match = _HUNK.match(line)
            if match:
                cursor = int(match.group(1))
        elif current is None or line.startswith(
            ("---", "+++", "index ", "new file", "deleted file", "similarity", "rename ")
        ):
            continue
        elif line.startswith("-"):
            if cursor is not None:
                lines[current].add(cursor)
                cursor += 1
        elif line.startswith("+"):
            if cursor is None:
                # A hunk that only adds: the file exists in the base, but this
                # block has no base coordinate of its own to compare against.
                lines[current].add(_CREATED)
            else:
                lines[current].add(cursor)
        else:
            if cursor is not None:
                cursor += 1
    return dict(lines)


@dataclass(frozen=True)
class Overlap:
    """How much of the reference the produced change also touches."""

    files_matched: set[str] = field(default_factory=set)
    matched_lines: int = 0
    reference_lines: int = 0

    @property
    def score(self) -> float | None:
        if self.reference_lines <= 0:
            return None
        return round(self.matched_lines / self.reference_lines, 6)


def overlap(produced: dict[str, set[int]], reference: dict[str, set[int]]) -> Overlap:
    matched_files: set[str] = set()
    matched_lines = 0
    reference_lines = 0
    for name, reference_set in reference.items():
        reference_lines += len(reference_set)
        shared = produced.get(name, set()) & reference_set
        if shared:
            matched_files.add(name)
            matched_lines += len(shared)
    return Overlap(matched_files, matched_lines, reference_lines)


def _run(argv: list[str], cwd: Path, timeout: float | None) -> subprocess.CompletedProcess | None:
    """Run a fixed argv with no shell; ``None`` means it could not run or timed out."""
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def produced_change(
    workspace: Path, timeout: float | None
) -> tuple[str, dict[str, set[int]]] | None:
    """The change the workspace holds over its base commit, read-only.

    ``None`` means the directory is not a git checkout, so there is no base to
    diff against. Untracked files count as created at :data:`_CREATED`, because
    an agent that adds a new module has changed something a patch reference may
    also add.
    """
    diff = _run(
        ["git", "--no-optional-locks", "diff", "--no-color", "--no-ext-diff", "HEAD"],
        workspace,
        timeout,
    )
    if diff is None or diff.returncode != 0:
        return None
    untracked = _run(
        ["git", "--no-optional-locks", "ls-files", "--others", "--exclude-standard"],
        workspace,
        timeout,
    )
    lines = changed_lines(diff.stdout or "")
    if untracked is not None and untracked.returncode == 0:
        for name in untracked.stdout.splitlines():
            if name.strip():
                lines.setdefault(name.strip(), set()).add(_CREATED)
    return diff.stdout or "", lines


class DiffEvaluator:
    """Scores the overlap between the produced change and a reference patch."""

    evaluator_id = EVALUATOR_ID
    kind = "diff"

    def evaluate(
        self,
        workspace: Path,
        *,
        out_dir: Path,
        timeout: float | None = None,
        reference_patch: str | Path | None = None,
        **inputs: Any,
    ) -> EvaluationResult:
        started = time.time()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if not reference_patch:
            return self._result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": "the task declares no reference patch"},
                started=started,
            )
        reference_path = Path(reference_patch)
        if not reference_path.is_file():
            return self._result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": f"reference patch not found: {reference_path}"},
                started=started,
            )
        try:
            reference_text = reference_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return self._result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": f"the reference patch could not be read: {exc}"},
                started=started,
            )
        reference_map = changed_lines(reference_text)
        if not reference_map:
            return self._result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={"reason": "the reference patch changes no file; it measures nothing"},
                started=started,
            )

        measured_change = produced_change(Path(workspace), timeout)
        if measured_change is None:
            return self._result(
                EvaluationVerdict.EVALUATOR_ERROR,
                details={
                    "reason": "the workspace is not a git checkout, so it has no base to diff "
                    "against and nothing to compare with the reference",
                    "workspace": str(workspace),
                },
                started=started,
            )
        produced_text, produced_map = measured_change

        measured = overlap(produced_map, reference_map)
        raw = (
            f"--- produced diff ---\n{produced_text}\n"
            f"--- reference patch ---\n{reference_text}\n"
        )
        raw_path = out_dir / "diff-report.txt"
        raw_path.write_text(raw, encoding="utf-8")
        produced_path = out_dir / "produced-diff.patch"
        produced_path.write_text(produced_text, encoding="utf-8")

        return self._result(
            # A diff is evidence about the change, never proof of correctness,
            # so the verdict stops at `partial` by construction (plan 16).
            EvaluationVerdict.PARTIAL if measured.score else EvaluationVerdict.FAILED,
            score=measured.score,
            passed=len(measured.files_matched),
            failed=max(len(reference_map) - len(measured.files_matched), 0),
            total=len(reference_map),
            details={
                "reference_files": len(reference_map),
                "produced_files": len(produced_map),
                "files_matched": sorted(measured.files_matched),
                "lines_in_reference": measured.reference_lines,
                "produced_lines_in_reference": measured.matched_lines,
                "note": "overlap is a qualitative signal; correctness is decided by tests",
            },
            raw=raw,
            started=started,
            artifacts={"report": str(raw_path), "produced_diff": str(produced_path)},
        )

    def _result(
        self,
        verdict: EvaluationVerdict,
        *,
        score: float | None = None,
        passed: int | None = None,
        failed: int | None = None,
        total: int | None = None,
        details: dict[str, Any] | None = None,
        raw: str | None = None,
        started: float,
        artifacts: dict[str, str] | None = None,
    ) -> EvaluationResult:
        return EvaluationResult(
            evaluator_id=self.evaluator_id,
            evaluator_version=EVALUATOR_VERSION,
            verdict=verdict,
            score=score,
            passed=passed,
            failed=failed,
            total=total,
            duration_seconds=round(time.time() - started, 3),
            details=dict(details or {}),
            raw=raw,
            artifacts=dict(artifacts or {}),
        )
