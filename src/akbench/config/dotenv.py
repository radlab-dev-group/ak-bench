"""Discovery and parsing of a project ``.env`` file.

A small, dependency-free subset of dotenv semantics: ``KEY=VALUE`` lines,
``export KEY=VALUE``, full-line and end-of-line comments, optional single or
double quotes around the value, and ``\\n`` / ``\\t`` escapes inside double
quotes. No variable interpolation: a value is what the file says, so a
miswritten file is easy to see.
"""

from __future__ import annotations

from pathlib import Path

ENV_FILE_NAME = ".env"


def find_dotenv_file(start: Path | None = None) -> Path | None:
    """Nearest ``.env`` at or above ``start`` (default: the current directory)."""
    origin = (start or Path.cwd()).resolve()
    for candidate in (origin, *origin.parents):
        path = candidate / ENV_FILE_NAME
        if path.is_file():
            return path
    return None


def _clean_value(value: str) -> str:
    """Drop the enclosing quotes or the trailing comment of a raw value."""
    if value and value[0] in "'\"":
        quote = value[0]
        end = value.find(quote, 1)
        inner = value[1:] if end == -1 else value[1:end]
        if quote == '"':
            inner = inner.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
        return inner
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    return value


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse ``.env`` content into a mapping; later lines win over earlier ones."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not key or not all(char.isalnum() or char == "_" for char in key):
            continue
        value = _clean_value(value.strip())
        values[key] = value
    return values


def load_dotenv(path: Path) -> dict[str, str]:
    """Read and parse one ``.env`` file."""
    return parse_dotenv(path.read_text(encoding="utf-8"))
