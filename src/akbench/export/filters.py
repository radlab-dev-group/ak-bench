"""What an export leaves out, on request (plan section 21).

An export is publishable by default: secrets are screened and everything else
is what the run was. Sometimes the publisher wants less than the truth — a
deck for people outside the project, an issue attached to a benchmark where
the agent's own words would leak a client's repository. Three switches narrow
what leaves the machine:

``prompts``
    The agent's own text: its final message and the prompt material inside a
    trace. Metrics, verdicts and timings stay, because they are the result.
``diffs``
    The patch the agent produced. The score it earned stays; the change itself
    does not travel.
``traces``
    The step-by-step record of what the agent did — ``agent_trace.jsonl``,
    ``tool_calls.jsonl`` and their siblings. They are the largest and the most
    revealing part of a run, and a summary answers the same questions.

Withheld material is counted, never silently dropped: the export says what it
left out, so a reader of the reduced document knows it is looking at a subset.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from typing import Any

#: What replaces withheld text, so a reader sees the shape of what is missing.
WITHHELD = "[withheld]"

#: Keys whose value is the agent's own words or the task text handed to it.
PROMPT_KEYS: frozenset[str] = frozenset(
    {
        "final_message",
        "finalMessage",
        "last_message",
        "prompt",
        "prompts",
        "task_text",
        "task_prompt",
        "user_message",
    }
)

#: Files whose content is the agent's own words: its final message, kept
#: beside the run because "what did it say" is part of what happened.
PROMPT_FILENAMES: frozenset[str] = frozenset({"last_message.txt"})

#: Filenames (and the kinds recorded from them) that are a trace of the run.
TRACE_FILENAMES: frozenset[str] = frozenset(
    {
        "agent_trace.jsonl",
        "agent_stdout.jsonl",
        "agent_stderr.log",
        "tool_calls.jsonl",
        "runtime_trace.jsonl",
        "events.jsonl",
        "stdout.log",
        "stderr.log",
        "router.log",
        # The packaged form of the same material: dropping the loose files and
        # carrying the archive of them out would be a filter in name only.
        "agent_traces.zip",
    }
)
TRACE_KINDS: frozenset[str] = frozenset(
    {"trace", "agent_trace", "runtime_trace", "tool_calls", "events", "stdout", "stderr"}
)

#: Filenames that carry the produced change, and the kind recorded from them.
DIFF_FILENAMES: frozenset[str] = frozenset(
    {
        "diff.patch",
        "solution.patch",
        "solution_diff.patch",
        "produced-diff.patch",
        # The workspace as the agent left it is the change, packed: the patch
        # filtered out and the solution carried out whole would say the same
        # thing with one hand behind the back.
        "solution.zip",
    }
)
DIFF_KINDS: frozenset[str] = frozenset({"diff"})
DIFF_KEYS: frozenset[str] = frozenset({"diff", "patch", "produced_diff", "solution_diff"})

_TRACE_GLOBS = ("*.trace.jsonl", "*_trace.jsonl")


def _basename(filename: str) -> str:
    """The name of an artifact, lowercased; a record may arrive as a path."""
    return filename.lower().replace("\\", "/").split("/")[-1]


def is_trace_artifact(filename: str, kind: str | None = None) -> bool:
    """Whether one artifact is a trace of what the agent did."""
    lowered = _basename(filename)
    if lowered in TRACE_FILENAMES:
        return True
    if kind and kind.lower() in TRACE_KINDS:
        return True
    return any(fnmatch.fnmatch(lowered, pattern) for pattern in _TRACE_GLOBS)


def is_prompt_artifact(filename: str) -> bool:
    """Whether one artifact is the agent's own text rather than a measurement."""
    return _basename(filename) in PROMPT_FILENAMES


def is_diff_artifact(filename: str, kind: str | None = None) -> bool:
    """Whether one artifact is the change the agent produced."""
    lowered = _basename(filename)
    return lowered in DIFF_FILENAMES or bool(kind and kind.lower() in DIFF_KINDS)


@dataclass(frozen=True)
class ExportFilters:
    """The three switches, all open by default.

    ``all_open`` is today's behaviour: an export with no flags is the export
    there was before these switches existed, apart from the ``withheld`` note
    that says so.
    """

    include_prompts: bool = True
    include_diffs: bool = True
    include_traces: bool = True

    @property
    def active(self) -> tuple[str, ...]:
        """Which switches are closed, named the way the CLI names them."""
        closed: list[str] = []
        if not self.include_prompts:
            closed.append("prompts")
        if not self.include_diffs:
            closed.append("diffs")
        if not self.include_traces:
            closed.append("traces")
        return tuple(closed)

    @property
    def keeps_artifacts(self) -> bool:
        """Whether an artifact of another kind can still be carried."""
        return self.include_diffs and self.include_traces

    def keeps_artifact(self, filename: str, kind: str | None = None) -> bool:
        if not self.include_prompts and is_prompt_artifact(filename):
            return False
        if not self.include_traces and is_trace_artifact(filename, kind):
            return False
        return not (not self.include_diffs and is_diff_artifact(filename, kind))


def withheld_kind(
    filename: str,
    kind: str | None,
    filters: ExportFilters,
    fallback: str = "artifacts",
) -> str:
    """Name the switch that dropped one artifact, so the export can say why."""
    if not filters.include_prompts and is_prompt_artifact(filename):
        return "prompts"
    if not filters.include_traces and is_trace_artifact(filename, kind):
        return "traces"
    if not filters.include_diffs and is_diff_artifact(filename, kind):
        return "diffs"
    return fallback


@dataclass
class Withheld:
    """What the filters removed, counted by what it was."""

    counts: dict[str, int] = field(default_factory=dict)

    def note(self, kind: str, count: int = 1) -> None:
        if count:
            self.counts[kind] = self.counts.get(kind, 0) + count

    def as_rows(self) -> list[dict[str, Any]]:
        return [
            {"kind": kind, "count": count} for kind, count in sorted(self.counts.items())
        ]

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self.counts.items()))


def without_prompts(value: Any, withheld: Withheld | None = None) -> Any:
    """A copy of a JSON-ish structure with the agent's own text replaced.

    Only the values go: a key that names prompt material stays, holding
    :data:`WITHHELD`, so the shape of the record survives and a reader can see
    that a run did have a final message.
    """
    notes = withheld if withheld is not None else Withheld()
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {name.lower() for name in PROMPT_KEYS}:
                if item not in (None, "", [], {}):
                    notes.note("prompt-fields")
                result[key] = WITHHELD if item is not None else None
                continue
            result[key] = without_prompts(item, notes)
        return result
    if isinstance(value, list):
        return [without_prompts(item, notes) for item in value]
    return value


def without_diffs(value: Any, withheld: Withheld | None = None) -> Any:
    """A copy with the produced change removed from a JSON-ish structure."""
    notes = withheld if withheld is not None else Withheld()
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {name.lower() for name in DIFF_KEYS}:
                if item not in (None, "", [], {}):
                    notes.note("diff-fields")
                result[key] = WITHHELD if item is not None else None
                continue
            result[key] = without_diffs(item, notes)
        return result
    if isinstance(value, list):
        return [without_diffs(item, notes) for item in value]
    return value


def filter_run(run: dict[str, Any], filters: ExportFilters, withheld: Withheld) -> dict[str, Any]:
    """One run, narrowed by the filters.

    The artifacts list is filtered rather than dropped: which files a run
    produced is part of its record, and a reader who sees the list knows what
    is missing. The other fields lose only what the switches name.
    """
    result = dict(run)
    if not filters.include_prompts:
        result = without_prompts(result, withheld)
    if not filters.include_diffs:
        result = without_diffs(result, withheld)
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        kept = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                kept.append(artifact)
                continue
            filename = str(artifact.get("filename") or artifact.get("path") or "")
            kind = str(artifact.get("kind") or "") or None
            if filters.keeps_artifact(filename.split("/")[-1], kind):
                kept.append(artifact)
            else:
                withheld.note(withheld_kind(filename, kind, filters))
        result["artifacts"] = kept
    return result


def filter_document(document: dict[str, Any], filters: ExportFilters) -> tuple[dict, dict]:
    """Narrow a built export document; returns it and what was withheld."""
    withheld = Withheld()
    if not filters.active:
        return document, {}

    result = dict(document)
    runs = result.get("runs")
    if isinstance(runs, list):
        result["runs"] = [
            filter_run(run, filters, withheld) if isinstance(run, dict) else run for run in runs
        ]
    # The top-level list mirrors the per-run ones, so it is narrowed with a
    # tally of its own: the runs above already said what left, and counting the
    # same file twice would report a withholding that never happened.
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        mirrors = Withheld()
        kept = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                kept.append(artifact)
                continue
            filename = str(artifact.get("path") or artifact.get("filename") or "")
            kind = str(artifact.get("kind") or "") or None
            if filters.keeps_artifact(filename, kind):
                kept.append(artifact)
            else:
                mirrors.note(withheld_kind(filename, kind, filters))
        result["artifacts"] = kept

    summary = {
        "filters": list(filters.active),
        "withheld": withheld.as_rows(),
    }
    return result, summary


#: Records whose prompt material can be lifted out of the file itself.
_JSON_RECORD_SUFFIXES = (".json",)


def filter_payload(
    filename: str, data: bytes, filters: ExportFilters, withheld: Withheld | None = None
) -> bytes | None:
    """The bytes of one artifact as the filters allow them, or ``None``.

    A file the filters exclude outright is not written. A JSON record that
    survives is stripped of the fields the switches name, so a copy of a run
    record asked to leave prompts out really does not contain them. Anything
    that is not JSON is carried unchanged: rewriting a log line by line would
    edit the evidence, and an export is not an editor.
    """
    notes = withheld if withheld is not None else Withheld()
    name = filename.split("/")[-1]
    if not filters.keeps_artifact(name):
        notes.note(withheld_kind(name, None, filters))
        return None
    if not filters.include_prompts or not filters.include_diffs:
        lowered = name.lower()
        if filters.include_prompts and not is_prompt_artifact(lowered):
            return data
        if lowered.endswith(_JSON_RECORD_SUFFIXES):
            try:
                parsed = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return data
            if not filters.include_prompts:
                parsed = without_prompts(parsed, notes)
            if not filters.include_diffs:
                parsed = without_diffs(parsed, notes)
            return json.dumps(parsed, indent=2, ensure_ascii=False).encode("utf-8")
    return data
