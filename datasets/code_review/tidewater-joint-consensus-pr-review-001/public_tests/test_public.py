"""Shape checks you can run before you hand the review in."""

from __future__ import annotations

import json
from pathlib import Path


def _root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "reviews" / "PR-118-joint-consensus").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared tidewater workspace")


ROOT = _root()
PR = ROOT / "reviews" / "PR-118-joint-consensus"


def test_the_change_under_review_is_there_to_read():
    assert (PR / "PR.md").is_file()
    assert (PR / "diff.patch").is_file()
    assert "+def configuration_in_force" in (PR / "diff.patch").read_text(encoding="utf-8")


def test_the_review_file_is_valid_json_of_the_right_shape():
    document = json.loads((ROOT / "review_findings.json").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    findings = document["findings"]
    assert isinstance(findings, list) and findings
    for finding in findings:
        assert finding["title"].strip()
        assert len(finding["detail"].strip()) > 40, (
            "a detail of forty characters is a comment, not a finding: say what breaks in a run"
        )
        assert finding.get("reference"), "name the rule: SPEC.md 7.x or ADR-0007"


def test_the_review_is_not_a_wall_of_text():
    document = json.loads((ROOT / "review_findings.json").read_text(encoding="utf-8"))
    assert len(document["findings"]) <= 10, "keep what you can defend"
