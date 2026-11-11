"""The finished part of the fixture: reading inside the base directory.

The suite deliberately never asks for a file outside the base directory,
so a path-escape defect is invisible here.
"""

from __future__ import annotations

from filebox import read_text


def test_reads_a_file_in_the_base_directory(tmp_path):
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    assert read_text(tmp_path, "note.txt") == "hello"


def test_reads_a_file_in_a_subdirectory(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "note.txt").write_text("nested", encoding="utf-8")
    assert read_text(tmp_path, "sub/note.txt") == "nested"
