"""The symptom a developer can reproduce: ../ reads outside the base."""

from __future__ import annotations

import pytest

from filebox import read_text


def test_a_parent_reference_is_refused(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError):
        read_text(base, "../secret.txt")


def test_a_file_inside_the_base_still_reads(tmp_path):
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    assert read_text(tmp_path, "note.txt") == "hello"
