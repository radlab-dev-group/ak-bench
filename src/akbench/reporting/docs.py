"""The documentation tree of the report: every document, one page each.

The report is read as a report, but the project is documented, and a reader
who opens the report on a machine without the checkout would otherwise lose
the writing that explains it. The docs tree renders the repository's own
documents as pages under ``docs/`` — a landing page with the table of
contents, and one page per document — with the same rules the rest of the
report obeys: no external asset, everything escaped, and a page for every
label.

The documents come from the checkout the report is written from: the files
the repository tracks, and a walk over the working tree when there is no git
history to ask. A document is the file at the address it was read from, so a
report written next to a different checkout says which files it held, and
nothing is invented for the ones it did not.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from akbench.reporting.markdown import render_markdown

# the trees a checkout holds that are not the project's own documents:
# vendored code, build output, the report itself and its data
_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    "data",
    "reports",
}


@dataclass(frozen=True)
class Document:
    """One document of the checkout: its address and its rendered body."""

    relpath: str
    title: str
    body: str
    headings: list[tuple[int, str, str]]


def discover_documents(root: Path) -> list[Document]:
    """Every document of one checkout, in a stable order the menu can show.

    Git is asked first, because it names the documents the repository tracks
    and skips the vendored trees by construction; the walk over the tree is
    the fallback for a checkout that is not one.
    """
    relpaths = _tracked_markdown(root)
    if relpaths is None:
        relpaths = _walk_markdown(root)
    documents: list[Document] = []
    for relpath in sorted(relpaths):
        source = (root / relpath).read_text(encoding="utf-8")
        title = _title_of(relpath, source)
        documents.append(
            Document(
                relpath=relpath,
                title=title,
                body=render_markdown(source),
                headings=_headings_of(source),
            )
        )
    return documents


def _tracked_markdown(root: Path) -> list[str] | None:
    """The Markdown files git tracks under ``root``, or ``None`` without git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "*.md"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    relpaths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return relpaths or None


def _walk_markdown(root: Path) -> list[str]:
    """Every ``*.md`` under ``root`` the walk may read, vendored trees aside."""
    relpaths: list[str] = []
    for path in sorted(root.rglob("*.md")):
        parts = path.relative_to(root).parts
        if any(part in _EXCLUDED_DIRS or part.startswith(".venv") for part in parts):
            continue
        relpaths.append(str(path.relative_to(root)))
    return relpaths


def _title_of(relpath: str, source: str) -> str:
    """The name a document gets in the menu: its heading, else its file name."""
    for line in source.splitlines():
        match = re.match(r"^#\s+(.*)$", line.strip())
        if match:
            return match.group(1).strip()
    return Path(relpath).stem.replace("-", " ").replace("_", " ").title()


def _headings_of(source: str) -> list[tuple[int, str, str]]:
    """The ``h2`` and deeper headings of one document, as the page anchors them."""
    headings: list[tuple[int, str, str]] = []
    used: dict[str, int] = {}
    for line in source.splitlines():
        match = re.match(r"^(#{2,6})\s+(.*)$", line.strip())
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "section"
        count = used.get(base, 0)
        used[base] = count + 1
        headings.append((level, base if count == 0 else f"{base}-{count}", title))
    return headings


DOCS_DIRECTORY = "docs"


def page_paths(documents: Sequence[Document]) -> dict[str, str]:
    """The address of one document's page, unique across the tree.

    The address mirrors the file's path so a reader who knows the checkout
    finds the page, and a collision (two paths that flatten to one name) is
    broken with a counter rather than by silently dropping a document.
    """
    taken: set[str] = set()
    paths: dict[str, str] = {}
    for document in documents:
        relpath = document.relpath
        stem = relpath[: -len(".md")] if relpath.endswith(".md") else relpath
        slug = re.sub(r"[^a-zA-Z0-9.]+", "-", stem).strip("-.").lower() or "document"
        candidate = slug
        suffix = 2
        while candidate in taken:
            candidate = f"{slug}-{suffix}"
            suffix += 1
        taken.add(candidate)
        paths[document.relpath] = f"{DOCS_DIRECTORY}/{candidate}/index.html"
    return paths


def group_of(relpath: str) -> str:
    """The part of the menu one document is listed under."""
    parts = Path(relpath).parts
    if len(parts) == 1:
        return "Project"
    if parts[0] == DOCS_DIRECTORY:
        return "Handbook"
    if parts[0] == ".plans":
        return "Plan"
    return parts[0].replace("_", " ").title()


def group_order(name: str) -> tuple[int, str]:
    """Project first, then the handbook, then everything else by name."""
    rank = {"Project": 0, "Handbook": 1}.get(name, 2)
    return (rank, name.lower())

