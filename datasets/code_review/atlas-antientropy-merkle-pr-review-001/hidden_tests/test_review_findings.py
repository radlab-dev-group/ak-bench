"""Grade review_findings.json against the defects planted in the PR.

Every golden defect is a set of concept groups; a finding matches a defect when
it touches every group. A finding can be credited with one defect only, so
restating one idea twenty times does not buy recall, and the number of findings
is capped, so listing the whole diff as "suspicious" does not either.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

MAX_FINDINGS = 10
REQUIRED_KEYS = ("title", "detail")


def _repo_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "atlas").is_dir():
            return candidate
    raise RuntimeError("hidden tests run inside a prepared atlas workspace")


def _goldens() -> list[dict]:
    path = Path(__file__).resolve().parent / "goldens" / "expected_findings.json"
    return json.loads(path.read_text(encoding="utf-8"))["defects"]


def _findings() -> list[dict]:
    path = _repo_root() / "review_findings.json"
    assert path.is_file(), "write your review to review_findings.json at the repository root"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), "the file must be a JSON object with a 'findings' list"
    findings = document.get("findings")
    assert isinstance(findings, list) and findings, "'findings' must be a non-empty list"
    for index, finding in enumerate(findings):
        assert isinstance(finding, dict), f"finding {index} is not an object"
        for key in REQUIRED_KEYS:
            value = finding.get(key)
            assert isinstance(value, str) and value.strip(), f"finding {index} needs a '{key}'"
    return findings


def _text(finding: dict) -> str:
    return " ".join(
        str(finding.get(key, "")) for key in ("title", "detail", "file", "reference", "severity")
    ).lower()


def _match(finding: str, groups: list[list[str]]) -> bool:
    return any(marker.lower() in finding for marker in groups[0]) and all(
        any(marker.lower() in finding for marker in group) for group in groups[1:]
    )


def _assignment() -> dict[str, int]:
    findings = [_text(finding) for finding in _findings()]
    credited: set[int] = set()
    taken: dict[str, int] = {}
    for defect in _goldens():
        for index, text in enumerate(findings):
            if index not in credited and _match(text, defect["groups"]):
                credited.add(index)
                taken[defect["id"]] = index
                break
    return taken


def test_the_review_is_a_review_and_not_a_list_of_everything():
    findings = _findings()
    assert len(findings) <= MAX_FINDINGS, (
        f"{len(findings)} findings: keep the ones you can defend and drop the rest"
    )
    titles = [str(finding["title"]).strip().lower() for finding in findings]
    assert len(set(titles)) == len(titles), "the same finding is listed more than once"


def _reference_pattern() -> re.Pattern[str]:
    path = Path(__file__).resolve().parent / "goldens" / "expected_findings.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    return re.compile(document["reference_pattern"], re.IGNORECASE)


def test_the_review_names_the_rule_it_says_was_broken():
    references = [
        str(finding.get("reference", "")) + " " + str(finding.get("detail", ""))
        for finding in _findings()
    ]
    assert any(_reference_pattern().search(reference) for reference in references), (
        "at least one finding has to cite the contract it invokes: "
        + next(
            document.get("reference_hint", "a named rule")
            for document in [json.loads((Path(__file__).resolve().parent / "goldens" / "expected_findings.json").read_text(encoding="utf-8"))]
        )
    )


@pytest.mark.parametrize("defect", [d["id"] for d in json.loads(
    (Path(__file__).resolve().parent / "goldens" / "expected_findings.json").read_text(
        encoding="utf-8"
    )
)["defects"]])
def test_the_review_found_the_defect(defect: str):
    taken = _assignment()
    assert defect in taken, (
        f"no finding describes {defect}: "
        + next(d["summary"] for d in _goldens() if d["id"] == defect)
    )
