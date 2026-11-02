"""A small, self-contained Markdown to HTML renderer for the report docs.

The reports are static files that must read from a USB stick, so the document
pages render their source here instead of pulling in a Markdown library or an
external asset. The renderer covers what this repository's documents use —
headings, lists, fenced code, pipe tables, blockquotes, inline code, emphasis
and links — and it escapes everything, because a document written in a hurry
is still untrusted input to a page that ships to a reader.
"""

from __future__ import annotations

import html
import re

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_AUTOLINK_RE = re.compile(r"(?<![\"(\w])https?://[^\s<>()\[\]]+")


def _slugify_heading(text: str) -> str:
    """An anchor id for one heading, unique per text in a document."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def _safe_href(href: str) -> str:
    """Keep the hrefs a document may mean, drop the ones a page must not run.

    A relative href is what a document uses to point at another document, and
    the report resolves it like any other; a scheme that is not a document
    scheme (``javascript:`` above all) is dropped to a no-op anchor.
    """
    scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", href)
    if scheme is None:
        return href
    return href if scheme.group(0).lower() in ("http:", "https:", "mailto:") else "#"


def _render_inline(text: str) -> str:
    """One line of Markdown: code, emphasis, links, escaped.

    Inline code is lifted out first and restored last, so the formatting
    markers inside a code span are never interpreted, only escaped.
    """
    spans: list[str] = []

    def lift(match: re.Match[str]) -> str:
        spans.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(spans) - 1}\x00"

    text = _INLINE_CODE_RE.sub(lift, text)
    text = html.escape(text)

    def link(match: re.Match[str]) -> str:
        label, href, title = match.group(1), match.group(2), match.group(3)
        quoted = f' title="{html.escape(title)}"' if title else ""
        return f'<a href="{_safe_href(href)}"{quoted}>{label}</a>'

    text = _LINK_RE.sub(link, text)

    def autolink(match: re.Match[str]) -> str:
        return f'<a href="{match.group(0)}">{match.group(0)}</a>'

    text = _AUTOLINK_RE.sub(autolink, text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)

    for index, span in enumerate(spans):
        text = text.replace(f"\x00{index}\x00", span)
    return text


def _split_table_row(line: str) -> list[str]:
    """The cells of one pipe-table row, without the framing pipes."""
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip() for cell in row.split("|")]


def _is_table_separator(line: str) -> bool:
    """A row of ``---`` cells: the line between a table head and its body."""
    if "|" not in line:
        return False
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def render_markdown(source: str) -> str:
    """The HTML body of one Markdown document, escaped end to end."""
    lines = source.splitlines()
    out: list[str] = []
    used_ids: dict[str, int] = {}
    in_list: str | None = None  # "ul" or "ol" while a list is open
    in_quote = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    def close_quote() -> None:
        nonlocal in_quote
        if in_quote:
            out.append("</blockquote>")
            in_quote = False

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # a fenced code block lifts everything until the closing fence
        if stripped.startswith("```"):
            close_list()
            close_quote()
            language = stripped[3:].strip()
            body: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                body.append(lines[index])
                index += 1
            index += 1
            label = f'<span class="code-lang">{html.escape(language)}</span>' if language else ""
            out.append(
                f'<div class="code-block">{label}<pre>'
                f"{html.escape(chr(10).join(body))}</pre></div>"
            )
            continue

        if not stripped:
            close_list()
            close_quote()
            index += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            close_quote()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            base = _slugify_heading(title)
            count = used_ids.get(base, 0)
            used_ids[base] = count + 1
            anchor = base if count == 0 else f"{base}-{count}"
            out.append(
                f'<h{level} id="{anchor}">{_render_inline(title)}</h{level}>'
            )
            index += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            close_list()
            close_quote()
            out.append("<hr />")
            index += 1
            continue

        if (
            index + 1 < len(lines)
            and "|" in stripped
            and not _is_table_separator(stripped)
            and _is_table_separator(lines[index + 1].strip())
        ):
            close_list()
            close_quote()
            header = _split_table_row(stripped)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip() and "|" in lines[index].strip():
                rows.append(_split_table_row(lines[index]))
                index += 1
            head_cells = "".join(
                f"<th>{_render_inline(cell)}</th>" for cell in header
            )
            body_cells = "".join(
                "<tr>"
                + "".join(f"<td>{_render_inline(cell)}</td>" for cell in row)
                + "</tr>"
                for row in rows
            )
            out.append(
                '<div class="table-wrap"><table class="docs">'
                f"<thead><tr>{head_cells}</tr></thead>"
                f"<tbody>{body_cells}</tbody></table></div>"
            )
            continue

        if stripped.startswith("> "):
            close_list()
            if not in_quote:
                out.append("<blockquote>")
                in_quote = True
            out.append(f"<p>{_render_inline(stripped[2:])}</p>")
            index += 1
            continue

        list_match = re.match(r"^(?:[-*+]|\d+[.)])\s+(.*)$", stripped)
        if list_match:
            close_quote()
            kind = "ul" if not re.match(r"^\d+[.)]", stripped) else "ol"
            if in_list != kind:
                close_list()
                out.append(f"<{kind}>")
                in_list = kind
            out.append(f"<li>{_render_inline(list_match.group(1))}</li>")
            index += 1
            continue

        close_list()
        close_quote()
        out.append(f"<p>{_render_inline(stripped)}</p>")
        index += 1

    close_list()
    close_quote()
    return "\n".join(out)
