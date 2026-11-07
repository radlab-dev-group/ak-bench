"""The ``.env`` parser: enough of dotenv to configure a connection, no magic."""

from __future__ import annotations

from pathlib import Path

from akbench.config.dotenv import find_dotenv_file, load_dotenv, parse_dotenv


def test_parses_assignments_comments_and_quotes() -> None:
    parsed = parse_dotenv(
        "# comment\n"
        "\n"
        "PLAIN=value\n"
        "export EXPORTED=value2\n"
        'DOUBLE="quoted value"   # trailing comment\n'
        "SINGLE='keep # inside'\n"
        "WITH_EQUALS=a=b\n"
        "EMPTY=\n"
        "not a pair\n"
    )
    assert parsed == {
        "PLAIN": "value",
        "EXPORTED": "value2",
        "DOUBLE": "quoted value",
        "SINGLE": "keep # inside",
        "WITH_EQUALS": "a=b",
        "EMPTY": "",
    }


def test_escapes_are_honoured_only_inside_double_quotes() -> None:
    assert parse_dotenv('A="line\\nbreak"')["A"] == "line\nbreak"
    assert parse_dotenv("B=raw\\nbreak")["B"] == "raw\\nbreak"


def test_later_line_wins() -> None:
    assert parse_dotenv("A=first\nA=second")["A"] == "second"


def test_load_dotenv_reads_the_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("AKBENCH_PG_PORT=5959\n", encoding="utf-8")
    assert load_dotenv(path) == {"AKBENCH_PG_PORT": "5959"}


def test_find_dotenv_searches_the_parents(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (tmp_path / ".env").write_text("A=1\n", encoding="utf-8")
    assert find_dotenv_file(nested) == (tmp_path / ".env").resolve()


def test_find_dotenv_is_none_without_a_file(tmp_path: Path) -> None:
    assert find_dotenv_file(tmp_path) is None
