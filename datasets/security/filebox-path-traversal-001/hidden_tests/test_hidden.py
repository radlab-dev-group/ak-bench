"""The vulnerability, proven from every side.

These tests fail on the base commit (the vulnerability is in the base
code) and pass once the escape is closed.
"""

from __future__ import annotations

import pytest

from filebox import read_text


def test_a_parent_reference_is_refused(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError):
        read_text(base, "../secret.txt")


def test_a_nested_climb_out_is_refused(tmp_path):
    base = tmp_path / "base"
    (base / "sub").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError):
        read_text(base, "sub/../../secret.txt")


def test_an_absolute_path_is_refused(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError):
        read_text(tmp_path, str(secret))


def test_an_absolute_path_inside_the_base_is_still_refused(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        read_text(tmp_path, str(note))


def test_a_dotdot_that_stays_inside_is_allowed(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    assert read_text(tmp_path, "sub/../note.txt") == "hello"


def test_files_inside_the_base_still_read(tmp_path):
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("deep", encoding="utf-8")
    assert read_text(tmp_path, "note.txt") == "hello"
    assert read_text(tmp_path, "sub/deep.txt") == "deep"


def test_a_missing_file_inside_the_base_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_text(tmp_path, "missing.txt")
