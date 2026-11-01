"""Rendering of the static HTML reports.

The output is a tree of plain files: no server, no JavaScript, no external
asset. A report opened a month later has to read the same as it does today,
and it has to be emailable.

Three things are deliberate:

- everything is escaped, because run records contain agent output;
- an absent value prints as ``not measured`` rather than blank, so a blank
  cell is never mistaken for a zero;
- failed runs and unverified configurations are rendered, never dropped. A
  report that let a reader miss them would be worse than no report.
"""

from __future__ import annotations

import html
import re
from pathlib import Path, PurePosixPath
from typing import Any

from akbench.reporting.data import (
    ExperimentReport,
    HistoryData,
    RunReport,
    SubjectReport,
    TaskReport,
    build_agent_report,
    build_category_report,
    build_difficulty_report,
    build_experiment_report,
    build_model_report,
    build_plugin_report,
    build_run_report,
    build_runtime_report,
    build_task_report,
    build_verdict_report,
    dashboard,
    duration_seconds,
    order_by_start,
    unverified_configurations,
    variant_comparison,
    variant_lookup,
    verdict_of,
)

STYLE_NAME = "assets/style.css"
ASSET_NAMES: tuple[str, ...] = (STYLE_NAME,)
NOT_MEASURED = "not measured"
CSS_TOKEN = "{{css}}"
ROOT_TOKEN = "{{root}}"

STYLE = """
/* AK-Bench report — a terminal read of the history, tuned for reading rather
   than for looking like a terminal. The palette stays phosphor-green and the
   type stays monospaced, because this is a machine record; the glow, the
   scanlines and the vignette are gone, because they cost contrast and a long
   table of numbers is read, not glanced at. Every value stays exactly as it
   was measured: a style that flatters a number would be a lie in a nicer font.
   A light scheme is used for print, because a black page wastes a toner. */
:root {
  --bg: #0a0e10; --panel: #0e1416; --raise: #121a1c;
  --fg: #cfe9d8; --bright: #f2fbf5; --muted: #7fa593;
  --line: #223a30; --line-soft: #17281f; --head: #14201b;
  --pass: #4ade80; --fail: #ff7a6e; --warn: #f5c65b; --accent: #3ddbc0;
  --row: rgba(255, 255, 255, .022);
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0; padding: 1.6rem 1.25rem 4rem; background: var(--bg); color: var(--fg);
  font: 15px/1.65 ui-monospace, "SFMono-Regular", "JetBrains Mono", Menlo, Consolas, monospace;
  -webkit-font-smoothing: antialiased;
}
main {
  max-width: 78rem; margin: 0 auto; border: 1px solid var(--line);
  border-radius: 6px; background: var(--panel); padding: 1.6rem 1.8rem 2.2rem;
}
h1 {
  font-size: 1.05rem; margin: 0 0 .3rem; letter-spacing: .14em; text-transform: uppercase;
  color: var(--bright);
}
h1::before { content: "> "; color: var(--accent); }
h2 {
  font-size: .82rem; margin: 2.4rem 0 .7rem; letter-spacing: .13em; text-transform: uppercase;
  color: var(--accent); border-bottom: 1px solid var(--line); padding-bottom: .35rem;
}
h3 {
  font-size: .76rem; margin: 1.3rem 0 .4rem; letter-spacing: .11em; text-transform: uppercase;
  color: var(--muted);
}
a { color: var(--accent); text-decoration: none; border-bottom: 1px solid transparent; }
a:hover { color: var(--bright); border-bottom-color: var(--accent); }
.nav {
  font-size: .8rem; color: var(--muted); margin-bottom: 1.5rem; padding-bottom: .7rem;
  letter-spacing: .06em; border-bottom: 1px solid var(--line-soft);
}
.nav::before { content: "PATH "; color: var(--muted); }
.subtitle { color: var(--muted); margin: 0 0 1.4rem; font-size: .88rem; word-break: break-all; }
/* wide run tables are the common case: they scroll instead of squeezing
   the numbers until they wrap, and their header stays on screen */
.table-wrap { overflow-x: auto; margin: .6rem 0 1.3rem; }
table { border-collapse: collapse; width: 100%; font-size: .86rem; }
th, td {
  border-bottom: 1px solid var(--line-soft); padding: .5rem .7rem;
  text-align: left; vertical-align: top; font-variant-numeric: tabular-nums;
}
th {
  position: sticky; top: 0; z-index: 1; background: var(--head); color: var(--accent);
  font-weight: 600; font-size: .71rem; letter-spacing: .1em; text-transform: uppercase;
  border-bottom: 1px solid var(--accent); white-space: nowrap;
}
th.sortable { cursor: pointer; user-select: none; }
th.sortable::after { content: " \\2195"; color: var(--line); }
th.sortable:hover { background: rgba(61, 219, 192, .12); }
th.sortable:focus-visible { outline: 1px solid var(--accent); outline-offset: -1px; }
th[aria-sort="ascending"]::after { content: " \\2191"; color: var(--accent); }
th[aria-sort="descending"]::after { content: " \\2193"; color: var(--accent); }
tbody tr:nth-child(even) { background: var(--row); }
tbody tr:hover { background: rgba(61, 219, 192, .08); }
td.num, th.num { text-align: right; }
.cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
  gap: .7rem; margin: 1.1rem 0 1.8rem;
}
.card {
  border: 1px solid var(--line); border-radius: 5px; padding: .7rem .9rem;
  background: var(--raise);
}
.card .label {
  color: var(--muted); font-size: .68rem; letter-spacing: .12em; text-transform: uppercase;
}
.card .value { font-size: 1.35rem; color: var(--bright); line-height: 1.3; }
.pass { color: var(--pass); }
.fail { color: var(--fail); }
.warn { color: var(--warn); }
.muted { color: var(--muted); }
.badge {
  display: inline-block; border: 1px solid var(--line); border-radius: 3px;
  padding: .05rem .45rem; font-size: .71rem; letter-spacing: .08em;
  text-transform: uppercase; color: var(--muted); white-space: nowrap;
}
.badge.warn { border-color: var(--warn); color: var(--warn); }
.badge.pass { border-color: var(--pass); color: var(--pass); }
.notice {
  border-left: 3px solid var(--warn); background: rgba(245, 198, 91, .07);
  padding: .75rem .95rem; margin: 1rem 0; font-size: .85rem; border-radius: 0 4px 4px 0;
}
code {
  font: .82rem/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-all; color: var(--bright); background: rgba(0, 0, 0, .3);
  padding: .05rem .25rem;
}
.note { color: var(--muted); font-size: .8rem; margin: -.4rem 0 1.2rem; }
.task-title { color: var(--bright); font-size: 1rem; margin: 0 0 .5rem; }
.task-description, .task-notes { max-width: 68rem; }
pre.prose {
  max-width: 68rem; margin: .4rem 0 1rem; padding: .8rem .95rem; white-space: pre-wrap;
  overflow-wrap: anywhere; background: var(--raise); border: 1px solid var(--line);
  border-radius: 4px; font-size: .84rem; color: var(--fg);
}
details { margin: .5rem 0 1.1rem; }
summary { cursor: pointer; color: var(--muted); font-size: .78rem; letter-spacing: .08em;
  text-transform: uppercase; }
ul.constraints { max-width: 68rem; margin: .3rem 0 1rem; padding-left: 1.2rem; }
ul.constraints li { margin: .15rem 0; }
.folded { cursor: help; border-bottom: 1px dotted var(--line); }
footer {
  margin-top: 2.6rem; color: var(--muted); font-size: .76rem; letter-spacing: .08em;
  border-top: 1px solid var(--line); padding-top: .8rem;
}
/* the ranking and its bars: a measurement drawn to scale, never decoration */
.place { font-size: 1.15rem; color: var(--muted); }
.place.top { color: var(--pass); }
.bars { display: grid; gap: .45rem; margin: .5rem 0 1.3rem; }
.bar-row {
  display: grid; grid-template-columns: minmax(9rem, 22rem) 1fr; gap: .8rem;
  align-items: center; font-size: .82rem;
}
.bar-row .who { color: var(--fg); overflow-wrap: anywhere; }
.bar {
  position: relative; height: .85rem; background: rgba(0, 0, 0, .4);
  border: 1px solid var(--line); min-width: 6rem; border-radius: 2px;
}
.bar > span { position: absolute; left: 0; top: 0; bottom: 0; background: var(--accent); }
.bar.cost > span { background: var(--warn); }
.bar-note { color: var(--muted); font-size: .76rem; margin: -.5rem 0 1.3rem; }
.cell .bar { margin-top: .3rem; }
.cell { min-width: 5.5rem; }
@media print {
  .bar { border-color: #999; background: #f2f2f2; }
  .bar > span { background: #00664f; }
  .bar.cost > span { background: #8a6100; }
  :root { --bg: #fff; --panel: #fff; --raise: #fafafa; --fg: #14171a; --bright: #000;
          --muted: #565c63; --line: #c2c8cc; --line-soft: #e2e6e8; --head: #f0f2f3;
          --accent: #00664f; --pass: #0a7d38; --warn: #8a6100; --fail: #b3261e;
          --row: #f7f8f9; }
  body { font-size: 11px; }
  main { border: none; padding: 0; }
  th { position: static; }
}
"""


SORT_SCRIPT = """
// Sorting of a report table: clicking a column header reorders the rows.
// This is the one script a report page carries, and it changes the order of
// rows and nothing else — no number is computed, fetched or altered here. A
// page read with scripting off still shows every row, in the order it was
// written in, which is the order the history recorded.
(function () {
  "use strict";

  var MISSING = Object.freeze({ missing: true });

  function text(cell) {
    return (cell.textContent || "").trim();
  }

  // A value the report could not measure never sorts as a zero: it goes last.
  function isMissing(value) {
    return (
      value === "" ||
      value === "not measured" ||
      value === "not started" ||
      value === "not recorded" ||
      value === "not evaluated" ||
      value === "\u2014"
    );
  }

  // "3 m 25 s", "1 h 2 m", "12.5 s", "1,234", "97.9%" -> a number; anything
  // else is null, so the caller can fall back to comparing the text.
  function asNumber(raw) {
    if (isMissing(raw)) return MISSING;
    var value = raw.replace(/,/g, "");
    var pattern =
      "^(?:(\\d+(?:\\.\\d+)?)\\s*h)?\\s*(?:(\\d+(?:\\.\\d+)?)\\s*m)?\\s*(?:(\\d+(?:\\.\\d+)?)\\s*s)?$";
    var duration = value.match(new RegExp(pattern));
    if (duration && (duration[1] || duration[2] || duration[3])) {
      return (
        (parseFloat(duration[1] || 0) * 3600) +
        (parseFloat(duration[2] || 0) * 60) +
        parseFloat(duration[3] || 0)
      );
    }
    var plain = value.replace(/%$/, "");
    if (/^-?\\d+(?:\\.\\d+)?$/.test(plain)) return parseFloat(plain);
    return null;
  }

  function column(table, index) {
    var out = [];
    var rows = table.tBodies[0] ? table.tBodies[0].rows : [];
    for (var i = 0; i < rows.length; i += 1) {
      out.push(rows[i].cells[index] ? text(rows[i].cells[index]) : "");
    }
    return out;
  }

  function isNumeric(values) {
    var parsed = false;
    for (var i = 0; i < values.length; i += 1) {
      var value = asNumber(values[i]);
      if (value === null) return false;
      if (value !== MISSING) parsed = true;
    }
    return parsed;
  }

  function sort(table, index, ascending) {
    var body = table.tBodies[0];
    if (!body) return;
    var values = column(table, index);
    var numeric = isNumeric(values);
    var rows = Array.prototype.slice.call(body.rows);
    var position = new Map();
    rows.forEach(function (row, index) { position.set(row, index); });

    rows.sort(function (left, right) {
      var a = values[position.get(left)];
      var b = values[position.get(right)];
      if (numeric) {
        var na = asNumber(a);
        var nb = asNumber(b);
        var aMissing = na === MISSING;
        var bMissing = nb === MISSING;
        if (aMissing && bMissing) return position.get(left) - position.get(right);
        if (aMissing) return 1;   // never measured, always after what was
        if (bMissing) return -1;
        return ascending ? na - nb : nb - na;
      }
      var compared = String(a).localeCompare(String(b), undefined, { numeric: true });
      if (compared !== 0) return ascending ? compared : -compared;
      return position.get(left) - position.get(right);
    });

    rows.forEach(function (row) { body.appendChild(row); });
    markHeaders(table, index, ascending);
  }

  function markHeaders(table, index, ascending) {
    var cells = table.tHead ? table.tHead.rows[0].cells : [];
    for (var i = 0; i < cells.length; i += 1) {
      cells[i].removeAttribute("data-dir");
      cells[i].setAttribute(
        "aria-sort",
        i === index ? (ascending ? "ascending" : "descending") : "none"
      );
    }
  }

  function activate(header, index) {
    var table = header.closest("table");
    var ascending = header.getAttribute("data-dir") !== "asc";
    sort(table, index, ascending);
  }

  document.addEventListener("click", function (event) {
    var header = event.target.closest ? event.target.closest("th.sortable") : null;
    if (header) activate(header, Array.prototype.indexOf.call(header.parentNode.cells, header));
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var header = event.target.closest ? event.target.closest("th.sortable") : null;
    if (!header) return;
    event.preventDefault();
    activate(header, Array.prototype.indexOf.call(header.parentNode.cells, header));
  });
})();
"""

def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def number(value: float | int | None, *, digits: int = 0) -> str:
    """Format a number, or say plainly that it was never measured."""
    if value is None:
        return NOT_MEASURED
    if isinstance(value, bool):
        return esc(value)
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.{digits}f}"


def percent(value: float | None) -> str:
    if value is None:
        return NOT_MEASURED
    return f"{value * 100:.1f}%"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return NOT_MEASURED
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)} m {remainder:.0f} s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)} h {int(minutes)} m"


def table(headers: list[str], rows: list[list[str]]) -> str:
    """A table; a header ending in ``#`` is right-aligned as a number."""
    if not headers or not rows:
        return '<p class="muted">nothing recorded</p>'

    def is_num(header: str) -> bool:
        return header.endswith("#")

    head = "".join(
        f'<th class="num sortable" tabindex="0" aria-sort="none" '
        f'title="sort by {esc(header[:-2].strip())}">'
        f"{esc(header[:-2].strip())}</th>"
        if is_num(header)
        else f'<th class="sortable" tabindex="0" aria-sort="none" '
        f'title="sort by {esc(header)}">{esc(header)}</th>'
        for header in headers
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="num">{cell}</td>' if is_num(header) else f"<td>{cell}</td>"
            for header, cell in zip(headers, row, strict=True)
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        f"{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def cards(items: list[tuple[str, str]]) -> str:
    rendered = "".join(
        f'<div class="card"><div class="label">{esc(label)}</div>'
        f'<div class="value">{value}</div></div>'
        for label, value in items
    )
    return f'<div class="cards">{rendered}</div>'


def page(
    title: str,
    body: str,
    *,
    generated_at: str | None = None,
    standalone: bool = False,
) -> str:
    """One page.

    ``standalone`` inlines the stylesheet and drops the navigation, for a file
    that must read on its own: the HTML form of an export.
    """
    nav = ""
    if not standalone:
        nav = (
            '<p class="nav">'
            f'<a href="{ROOT_TOKEN}index.html">dashboard</a> · '
            f'<a href="{ROOT_TOKEN}agents/index.html">agents</a> · '
            f'<a href="{ROOT_TOKEN}runtimes/index.html">runtimes</a> · '
            f'<a href="{ROOT_TOKEN}plugins/index.html">plugins</a> · '
            f'<a href="{ROOT_TOKEN}models/index.html">models</a> · '
            f'<a href="{ROOT_TOKEN}tasks/index.html">tasks</a> · '
            f'<a href="{ROOT_TOKEN}{RUNS_DIRECTORY}/index.html">runs</a></p>'
        )
    head = (
        f"<style>{STYLE}</style>" if standalone else f'<link rel="stylesheet" href="{CSS_TOKEN}">'
    )
    if standalone:
        # a standalone page is one file: there is no tree to address into, and a
        # token left in an href would be shown to the reader as literal text
        body = body.replace(ROOT_TOKEN, "")
    stamp = f"<footer>generated {esc(generated_at)} from the recorded history</footer>"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{esc(title)}</title>"
        f"{head}</head>"
        f"<body><main>{nav}{body}{stamp}</main>"
        f"<script>{SORT_SCRIPT}</script></body></html>\n"
    )


def _badges(statuses: dict[str, int] | list[str]) -> str:
    items = sorted(statuses.items()) if isinstance(statuses, dict) else [(s, 0) for s in statuses]
    if not items:
        return NOT_MEASURED
    parts = []
    for status, count in items:
        css = "pass" if status == "verified" else "warn"
        label = f"{status} x {count}" if count else str(status)
        parts.append(f'<span class="badge {css}">{esc(label)}</span>')
    return " ".join(parts)


NOTE_LIMIT = 160


def _note_cell(text: Any) -> str:
    """A long note, folded to one readable line with its full text kept.

    The plugin notes of this installation run to three hundred characters and
    one of them decides how much a row is worth, so the whole of it stays in
    the document (and in the ``title``); only its shape changes.
    """
    value = "" if text is None else str(text)
    if not value:
        return ""
    if len(value) <= NOTE_LIMIT:
        return esc(value)
    folded = value[:NOTE_LIMIT].rstrip()
    return (
        f'<span class="folded" title="{esc(value)}">'
        f"{esc(folded)} <span class='muted'>&hellip;</span></span>"
    )


def _notice(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return '<p class="pass">every recorded configuration states it was verified.</p>'
    rows = [
        [
            esc(item.get("kind")),
            esc(item.get("subject")),
            f'<span class="badge warn">{esc(item.get("status"))}</span>',
            esc(item.get("run_uid") or ""),
            _note_cell(item.get("note")),
        ]
        for item in findings
    ]
    return (
        '<div class="notice"><strong>Configurations that are not verified.</strong> '
        "They stay in the report, because a result produced under them is only as "
        "trustworthy as they are.</div>" + table(["kind", "subject", "status", "run", "note"], rows)
    )


def _comparison_table(
    rows: list[dict[str, Any]], label: str, directory: str | None = None
) -> str:
    """A comparison table; with a directory, the label links to that subject's
    page. Without one it stays plain text, because a link to a page that was
    never written is a broken promise, not a navigation aid."""
    return table(
        [
            label,
            "runs #",
            "evaluated #",
            "passed #",
            "success rate",
            "mean time",
            "tokens #",
            "statuses",
        ],
        [
            [
                _link_to(directory, row.get(label))
                if directory
                else esc(row.get(label)),
                number(row.get("runs") or 0),
                number(row.get("evaluated") or 0),
                number(row.get("passed") or 0),
                percent(row.get("success_rate")),
                duration(row.get("mean_duration_seconds")),
                number(row.get("total_tokens")),
                esc(", ".join(row.get("statuses") or [])),
            ]
            for row in rows
        ],
    )


def _bar(fraction: float | None, *, css: str = "") -> str:
    """One horizontal bar, drawn from a fraction of the largest value in a column.

    A value that was not measured keeps its width at zero: an empty bar and a
    zero bar would look the same otherwise.
    """
    classes = " ".join(part for part in ("bar", css) if part)
    if fraction is None:
        return f'<div class="{classes}"><span style="width: 0"></span></div>'
    width = max(0.0, min(1.0, fraction)) * 100
    return f'<div class="{classes}"><span style="width: {width:.1f}%"></span></div>'


def _cell_bar(rendered: str, fraction: float | None, *, css: str = "") -> str:
    """A value with its bar underneath: the number stays the readable part."""
    return f'<div class="cell">{rendered}{_bar(fraction, css=css)}</div>'


def _fraction(value: float | None, maximum: float | None) -> float | None:
    """``value`` against the largest value of the column, ``None`` stays ``None``."""
    if value is None or not maximum:
        return None
    return value / maximum


def _chart(rows: list[dict[str, Any]], key: str, *, css: str = "") -> str:
    """A bar chart of one measure across the ranked configurations."""
    values = [row.get(key) for row in rows]
    measured = [value for value in values if value is not None]
    maximum = max(measured) if measured else None
    parts = [
        '<div class="bar-row"><span class="who">'
        + esc(row.get("config"))
        + "</span>"
        + _bar(_fraction(row.get(key), maximum), css=css)
        + "</div>"
        for row in rows
    ]
    return f'<div class="bars">{"".join(parts)}</div>'


def _ranked_rows(rows: list[dict[str, Any]]) -> list[list[str]]:
    table_rows: list[list[str]] = []
    for row in rows:
        place = row.get("place")
        place_cell = (
            f'<span class="place top">{place}</span>'
            if place == 1
            else f'<span class="place">{place if place is not None else "&mdash;"}</span>'
        )
        label = esc(row.get("config"))
        if row.get("is_baseline"):
            label += ' <span class="badge">baseline</span>'
        table_rows.append(
            [
                place_cell,
                label,
                number(row.get("runs") or 0),
                number(row.get("evaluated") or 0),
                percent(row.get("success_rate")),
                duration(row.get("mean_duration_seconds")),
                number(row.get("total_tokens")),
                esc(row.get("vs_baseline") or ""),
            ]
        )
    return table_rows


def _ranking(runs: list[dict[str, Any]], variants: list[dict[str, Any]]) -> str:
    """The place of every configuration, then the same numbers drawn to scale."""
    rows = variant_comparison(runs, variants)
    if not rows:
        return '<p class="muted">nothing recorded</p>'
    if not any(row.get("place") is not None for row in rows):
        return (
            '<p class="muted">no configuration was evaluated, so no place can be '
            "stated; the runs are listed below as they were recorded</p>"
        )
    return (
        table(
            [
                "place",
                "configuration",
                "runs #",
                "evaluated #",
                "success rate",
                "mean time",
                "tokens #",
                "against the baseline",
            ],
            _ranked_rows(rows),
        )
        + "<h3>Success rate</h3>"
        + _chart(rows, "success_rate")
        + "<h3>Mean wall-clock time</h3>"
        + _chart(rows, "mean_duration_seconds", css="cost")
        + '<p class="bar-note">each bar is measured against the largest value in its own '
        "column; time and tokens are compared only within this experiment</p>"
    )


def _leaderboard(data: HistoryData) -> str:
    """Every configuration of every experiment, best first: the front-page answer.

    A place belongs to the experiment that measured it. There is deliberately
    no league across experiments: two experiments that did not share a task
    set, a model or a day are not comparable, and a merged ranking would
    invent a comparison the runs never supported.
    """
    rows: list[list[str]] = []
    for experiment in data.experiments:
        uid = str(experiment.get("uid"))
        ranked = variant_comparison(data.runs_for_experiment(uid), data.variants_for(uid))
        for row in ranked:
            place = row.get("place")
            place_cell = (
                f'<span class="place top">{place}</span>'
                if place == 1
                else f'<span class="place">{place if place is not None else "&mdash;"}</span>'
            )
            label = esc(row.get("config"))
            if row.get("is_baseline"):
                label += ' <span class="badge">baseline</span>'
            rows.append(
                [
                    place_cell,
                    _experiment_link(uid),
                    label,
                    number(row.get("runs") or 0),
                    number(row.get("evaluated") or 0),
                    _cell_bar(percent(row.get("success_rate")), row.get("success_rate")),
                    duration(row.get("mean_duration_seconds")),
                    number(row.get("total_tokens")),
                    esc(row.get("vs_baseline") or ""),
                ]
            )
    if not rows:
        return (
            '<p class="muted">nothing recorded yet: a ranking needs runs, and a '
            "place needs an evaluated run. Run an experiment with --store.</p>"
        )
    return (
        table(
            [
                "place",
                "experiment",
                "configuration",
                "runs #",
                "evaluated #",
                "success rate",
                "mean time",
                "tokens #",
                "against the baseline",
            ],
            rows,
        )
        + '<p class="bar-note">a place is stated within its own experiment and only '
        "for a configuration with an evaluated run; &mdash; means nothing was "
        "evaluated, which is not the same as failing</p>"
    )


def _experiment_link(uid: Any) -> str:
    """A link to an experiment report, addressed from the root of the tree.

    The address is a token-prefixed one because the same link appears on the
    dashboard, on a subject page two directories down and on a run page: a path
    relative to the page that wrote it is right in one of those and broken in
    the others.
    """
    return f'<a href="{ROOT_TOKEN}experiments/{esc(uid)}/index.html">{esc(uid)}</a>'


def render_index(data: HistoryData, *, generated_at: str | None = None) -> str:
    stats = dashboard(data)
    body = [
        "<h1>AK-Bench dashboard</h1>",
        '<p class="subtitle">the recorded history: experiments, runs, agents, '
        "runtimes, plugins and models</p>",
        cards(
            [
                ("experiments", number(stats["experiments"])),
                ("runs", number(stats["runs"])),
                ("evaluated", number(stats["evaluated"])),
                ("success rate", percent(stats["success_rate"])),
                ("tasks", number(stats["tasks"])),
                ("total time", duration(stats["total_duration_seconds"])),
                ("mean time", duration(stats["mean_duration_seconds"])),
                ("tokens", number(stats["total_tokens"])),
                ("cost", "not recorded"),
            ]
        ),
        f'<p class="muted">{esc(stats["cost"]["reason"])}</p>',
        "<h2>Configuration ranking</h2>",
        _leaderboard(data),
        "<h2>Verdicts</h2>",
        table(
            ["verdict", "runs #", "share of evaluated"],
            [
                [
                    _link_to("verdicts", verdict),
                    number(count),
                    percent(count / stats["evaluated"] if stats["evaluated"] else None),
                ]
                for verdict, count in sorted(stats["verdicts"].items())
            ],
        ),
        "<h2>Experiments</h2>",
        table(
            ["experiment", "type", "runs #", "verdicts", "updated"],
            [
                [
                    _experiment_link(row.get("uid")),
                    esc(row.get("type")),
                    number(row.get("runs") or 0),
                    _verdict_summary(row.get("verdicts") or {}),
                    esc(row.get("updated_at")),
                ]
                for row in data.experiments
            ],
        )
        if data.experiments
        else '<p class="muted">nothing recorded</p>',
        "<h2>Results by category</h2>",
        _comparison_table(stats["by_category"], "category", directory="categories"),
        "<h2>Results by difficulty</h2>",
        _comparison_table(stats["by_difficulty"], "difficulty", directory="difficulties"),
        "<h2>Agent comparison</h2>",
        _comparison_table(stats["agents"], "agent", directory="agents"),
        "<h2>Runtime and router comparison</h2>",
        _comparison_table(stats["runtimes"], "runtime", directory="runtimes"),
        "<h2>Plugin comparison</h2>",
        table(
            ["plugin", "runs #", "enabled runs #", "versions", "verification"],
            [
                [
                    _link_to("plugins", row.get("plugin")),
                    number(row.get("runs") or 0),
                    number(row.get("enabled_runs") or 0),
                    esc(", ".join(row.get("versions") or []) or NOT_MEASURED),
                    _badges(row.get("verification_statuses") or {}),
                ]
                for row in stats["plugins"]
            ],
        ),
        "<h2>Model comparison</h2>",
        table(
            ["requested", "observed", "runs #", "source", "verification"],
            [
                [
                    _link_to("models", row.get("requested")),
                    esc(row.get("observed")),
                    number(row.get("runs") or 0),
                    esc(", ".join(row.get("sources") or []) or NOT_MEASURED),
                    _badges(row.get("verification_statuses") or {}),
                ]
                for row in stats["models"]
            ],
        ),
        "<h2>Recent experiments</h2>",
        table(
            ["experiment", "title", "updated"],
            [
                [
                    _experiment_link(row.get("uid")),
                    esc(row.get("title")),
                    esc(row.get("updated_at")),
                ]
                for row in stats["recent_experiments"]
            ],
        ),
        "<h2>Not verified</h2>",
        _notice(stats["unverified_configurations"]),
    ]
    return page("AK-Bench dashboard", "".join(body), generated_at=generated_at)


RUNS_DIRECTORY = "runs"


def _run_link(run: dict[str, Any]) -> str:
    """The uid of a run, as a link to that run's own page.

    The page is addressed from the root of the tree, so a run reached from a
    task page, an experiment page or a subject page opens the same document.
    """
    uid = run.get("uid")
    if not uid:
        return esc(run.get("uid"))
    return f'<a href="{ROOT_TOKEN}{RUNS_DIRECTORY}/{esc(uid)}/index.html">{esc(uid)}</a>'


def _link_to(directory: str, label: Any, path: str | None = None) -> str:
    """A link to a page addressed from the root of the tree.

    The directory of a subject page is the slug of its label; a task page is
    written under the raw task uid, so it passes ``path`` explicitly. Getting
    this wrong is not cosmetic: it points at a file that was never written.
    """
    target = slugify(str(label)) if path is None else str(path)
    return (
        f'<a href="{ROOT_TOKEN}{esc(directory)}/{esc(target)}/index.html">'
        f"{esc(label)}</a>"
    )


def render_run(report: RunReport, *, generated_at: str | None = None) -> str:
    """Everything that belongs to one run, on one page."""
    run = report.run
    evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), dict) else {}
    observations = (
        run.get("observations") if isinstance(run.get("observations"), dict) else {}
    )
    verdict = verdict_of(run)
    verdict_css = "pass" if verdict == PASSED else ("fail" if verdict else "muted")
    body = [
        "<h1>Run</h1>",
        f'<p class="subtitle">{esc(run.get("uid"))}</p>',
        cards(
            [
                (
                    "verdict",
                    f'<span class="{verdict_css}">{esc(verdict or "not evaluated")}</span>',
                ),
                ("score", number(evaluation.get("score"), digits=3)),
                ("time", duration(duration_seconds(run))),
                ("tokens", number(observations.get("total_tokens"))),
                ("tool calls", number(observations.get("tool_call_count"))),
                ("status", esc(run.get("status"))),
            ]
        ),
        "<h2>Where this run belongs</h2>",
        table(
            ["field", "value"],
            [
                [
                    "experiment",
                    _experiment_link(run.get("experiment_uid"))
                    if run.get("experiment_uid")
                    else NOT_MEASURED,
                ],
                [
                    "task",
                    _link_to("tasks", run.get("task_uid"), path=str(run.get("task_uid"))
                    )
                    if run.get("task_uid")
                    else NOT_MEASURED,
                ],
                ["parameters", _parameters_cell(report.parameters)],
                ["variant", esc(run.get("variant_uid"))],
                [
                    "agent",
                    _link_to("agents", run.get("agent"))
                    if run.get("agent")
                    else NOT_MEASURED,
                ],
                [
                    "runtime",
                    _link_to("runtimes", run.get("runtime_id"))
                    if run.get("runtime_id")
                    else NOT_MEASURED,
                ],
                ["mode", esc(run.get("mode"))],
                [
                    "repetition",
                    number(run.get("repetition"))
                    if run.get("repetition") is not None
                    else NOT_MEASURED,
                ],
                ["session", esc(run.get("session_id"))],
                ["manifest digest", f'<code>{esc(run.get("manifest_digest"))}</code>'],
            ],
        ),
        "<h2>Evaluation</h2>",
        table(
            ["field", "value"],
            [
                [
                    "verdict",
                    f'<span class="{verdict_css}">{esc(verdict or "not evaluated")}</span>',
                ],
                ["score", number(evaluation.get("score"), digits=4)],
                ["tests passed", number(evaluation.get("passed"))],
                ["tests failed", number(evaluation.get("failed"))],
                ["tests total", number(evaluation.get("total"))],
            ],
        )
        if evaluation
        else '<p class="muted">this run was never evaluated: it has no verdict and no score</p>',
        "<h2>What the agent reported</h2>",
        table(
            ["field", "value"],
            [
                ["started", esc(run.get("started_at"))],
                ["finished", esc(run.get("finished_at"))],
                ["wall clock", duration(duration_seconds(run))],
                ["input tokens", number(observations.get("input_tokens"))],
                ["total tokens", number(observations.get("total_tokens"))],
                ["tool calls", number(observations.get("tool_call_count"))],
                [
                    "exit code",
                    number(run.get("exit_code"))
                    if run.get("exit_code") is not None
                    else NOT_MEASURED,
                ],
                ["failure class", esc(run.get("failure_class") or "none")],
                ["error", esc(run.get("error_message") or "")],
            ],
        ),
    ]

    if report.model_state:
        model = report.model_state
        body.append("<h2>Model</h2>")
        body.append(
            table(
                ["requested", "observed", "source", "verification"],
                [
                    [
                        esc(model.get("requested_model")),
                        esc(model.get("observed_model")),
                        esc(model.get("value_source")),
                        f'<span class="badge {_badge_css(model.get("verification_status"))}">'
                        f"{esc(model.get('verification_status'))}</span>",
                    ]
                ],
            )
        )
    if report.plugin_states:
        body.append("<h2>Plugins observed</h2>")
        body.append(
            table(
                ["plugin", "version", "enabled", "verification", "note"],
                [
                    [
                        _link_to("plugins", state.get("plugin_id")),
                        esc(state.get("plugin_version")),
                        "yes" if state.get("enabled") else "no",
                        f'<span class="badge {_badge_css(state.get("verification_status"))}">'
                        f"{esc(state.get('verification_status'))}</span>",
                        _note_cell(state.get("note")),
                    ]
                    for state in report.plugin_states
                ],
            )
        )
    if report.run.get("artifacts"):
        body.append("<h2>Artifacts</h2>")
        body.append(
            table(
                ["kind", "path", "checksum"],
                [
                    [
                        esc(artifact.get("kind")),
                        f'<code>{esc(artifact.get("path"))}</code>',
                        esc(artifact.get("checksum")),
                    ]
                    for artifact in run.get("artifacts") or []
                ],
            )
        )
    body.append("<h2>Not verified</h2>")
    body.append(_notice(report.unverified))
    return page(f"Run {run.get('uid')}", "".join(body), generated_at=generated_at)


def _parameters_cell(values: Any) -> str:
    """The factor values a run was executed under, one readable line."""
    if values is None:
        return '<span class="muted">not recorded</span>'
    if isinstance(values, dict):
        if not values:
            return '<span class="muted">(reference: no factor)</span>'
        return esc(", ".join(f"{key}={value}" for key, value in sorted(values.items())))
    return esc(values)


def _started_cell(run: dict[str, Any]) -> str:
    """When the run started, trimmed to the precision a reader compares at."""
    started = run.get("started_at")
    if not started:
        return '<span class="muted">not started</span>'
    text = str(started).replace("T", " ")
    return esc(text[:19])


RUN_TAIL = [
    "repetition #",
    "status",
    "verdict",
    "score #",
    "time",
    "tokens #",
    "failure class",
    "error",
]


def _runs_headers(*, show_task: bool = True, show_agent: bool = True) -> list[str]:
    """The columns of a run table; a header ending in ``#`` is a number."""
    headers = ["run", "parameters", "started"]
    if show_task:
        headers.append("task")
    if show_agent:
        headers.append("agent")
    return headers + RUN_TAIL


def _run_rows(
    runs: list[dict[str, Any]],
    lookup: dict[str, Any],
    *,
    show_task: bool = True,
    show_agent: bool = True,
) -> list[list[str]]:
    """The cells of a run table, in the order the caller passed the runs.

    One definition of a run row, used by every page that lists runs — a task,
    an experiment, a subject, the listing of all of them — so their columns
    cannot drift apart. The parameters of a run are its variant's factor
    values: a reader comparing two runs has to see which configuration each of
    them was, or the table is a list of unexplained numbers.
    """
    rows: list[list[str]] = []
    for run in runs:
        evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), dict) else {}
        observations = (
            run.get("observations") if isinstance(run.get("observations"), dict) else {}
        )
        row = [
            _run_link(run),
            _parameters_cell(lookup.get(str(run.get("variant_uid")))),
            _started_cell(run),
        ]
        if show_task:
            row.append(esc(run.get("task_uid")))
        if show_agent:
            row.append(esc(run.get("agent")))
        row += [
            number(run.get("repetition")) if run.get("repetition") is not None else NOT_MEASURED,
            esc(run.get("status")),
            esc(verdict_of(run)),
            number(evaluation.get("score"), digits=3),
            duration(duration_seconds(run)),
            number(observations.get("total_tokens")),
            esc(run.get("failure_class")),
            esc(run.get("error_message") or ""),
        ]
        rows.append(row)
    return rows


def _runs_table(
    runs: list[dict[str, Any]],
    variants: list[dict[str, Any]] | None = None,
    *,
    show_task: bool = True,
    show_agent: bool = True,
) -> str:
    """A run table in the order the caller passed the runs."""
    return table(
        _runs_headers(show_task=show_task, show_agent=show_agent),
        _run_rows(
            runs,
            variant_lookup(variants or []),
            show_task=show_task,
            show_agent=show_agent,
        ),
    )


def _all_variants(data: HistoryData) -> dict[str, Any]:
    """Every variant of every recorded experiment, as one uid to values map."""
    collected = [
        variant for rows in (data.variants or {}).values() for variant in rows
    ]
    return variant_lookup(collected)


def _directory_for(attribute: str) -> str:
    """The directory a subject page of this attribute lives in."""
    return {"category": "categories", "difficulty": "difficulties"}[attribute]


def _subject_listing(title: str, data: HistoryData, attribute: str) -> str:
    """A page listing every category or difficulty with its runs."""
    label_key = {"category": "by_category", "difficulty": "by_difficulty"}[attribute]
    rows = dashboard(data)[label_key]
    return render_listing(
        title,
        f"every recorded {attribute.lower()}; a row opens its runs",
        [
            [
                _link_to(_directory_for(attribute), row.get(attribute)),
                number(row.get("runs") or 0),
                number(row.get("evaluated") or 0),
                number(row.get("passed") or 0),
                percent(row.get("success_rate")),
                duration(row.get("mean_duration_seconds")),
                number(row.get("total_tokens")),
            ]
            for row in rows
        ],
        [
            attribute,
            "runs #",
            "evaluated #",
            "passed #",
            "success rate",
            "mean time",
            "tokens #",
        ],
    )


def _verdict_listing(data: HistoryData) -> str:
    """A page listing every verdict with the runs that carry it."""
    counts: dict[str, int] = {}
    for run in data.runs:
        verdict = verdict_of(run)
        if verdict is not None:
            counts[verdict] = counts.get(verdict, 0) + 1
    return render_listing(
        "Verdicts",
        "every verdict and the runs that carry it; a row opens those runs",
        [
            [
                _link_to("verdicts", verdict),
                number(count),
                percent(count / len(data.runs) if data.runs else None),
            ]
            for verdict, count in sorted(counts.items())
        ],
        ["verdict", "runs #", "share of all runs"],
    )


def _not_passed(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        run
        for run in runs
        if verdict_of(run) != PASSED
        or run.get("status") != "completed"
        or run.get("failure_class")
    ]


PASSED = "passed"


def _artifact_rows(runs: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [
            esc(run.get("uid")),
            esc(artifact.get("kind")),
            f'<code>{esc(artifact.get("path"))}</code>',
            esc(artifact.get("checksum")),
        ]
        for run in runs
        for artifact in run.get("artifacts") or []
    ]


def _verdict_summary(verdicts: dict[str, Any]) -> str:
    return esc(", ".join(f"{key}:{value}" for key, value in sorted(verdicts.items())))


def _experiment_subtitle(experiment: dict[str, Any]) -> str:
    title = experiment.get("title") or ""
    return f'<p class="subtitle">{esc(experiment.get("uid"))} - {esc(title)}</p>'


def _variant_run_count(runs: list[dict[str, Any]], variant_uid: Any) -> int:
    return sum(1 for run in runs if run.get("variant_uid") == variant_uid)


def render_experiment(
    report: ExperimentReport, *, generated_at: str | None = None, standalone: bool = False
) -> str:
    experiment = report.experiment
    summary = report.summary
    body = [
        "<h1>Experiment</h1>",
        _experiment_subtitle(experiment),
        cards(
            [
                ("runs", number(summary.get("runs"))),
                ("evaluated", number(summary.get("evaluated"))),
                ("success rate", percent(summary.get("success_rate"))),
                ("mean time", duration(summary.get("mean_duration_seconds"))),
                ("tokens", number(summary.get("total_tokens"))),
            ]
        ),
        "<h2>Configuration ranking</h2>",
        _ranking(report.runs, report.variants),
        "<h2>Descriptor and validity</h2>",
        table(
            ["field", "value"],
            [
                ["uid", esc(experiment.get("uid"))],
                ["type", esc(experiment.get("type"))],
                ["descriptor", esc(experiment.get("descriptor"))],
                ["config hash", f'<code>{esc(experiment.get("config_hash"))}</code>'],
                ["validity", esc(experiment.get("validity"))],
                ["created", esc(experiment.get("created_at"))],
                ["updated", esc(experiment.get("updated_at"))],
            ],
        ),
        "<h2>Variants</h2>",
        table(
            ["variant", "values", "config hash", "baseline", "runs #"],
            [
                [
                    esc(variant.get("uid")),
                    _values(variant.get("values")),
                    f'<code>{esc(variant.get("config_hash"))}</code>',
                    "yes" if variant.get("is_baseline") else "no",
                    number(_variant_run_count(report.runs, variant.get("uid"))),
                ]
                for variant in report.variants
            ],
        ),
        "<h2>Pinned descriptors</h2>",
        table(
            ["kind", "id", "version", "digest"],
            [
                [
                    esc(row.get("kind")),
                    esc(row.get("id")),
                    esc(row.get("version")),
                    f'<code>{esc(row.get("digest"))}</code>',
                ]
                for row in report.snapshots
            ],
        ),
        "<h2>Metrics</h2>",
        table(
            [
                "metric",
                "group",
                "unit",
                "runs #",
                "measured #",
                "availability",
                "mean #",
                "deviation #",
                "min #",
                "max #",
            ],
            [
                [
                    esc(row.get("metric")),
                    esc(row.get("group")),
                    esc(row.get("unit")),
                    number(row.get("runs") or 0),
                    number(row.get("measured") or 0),
                    percent(row.get("availability")),
                    number(row.get("mean"), digits=4),
                    number(row.get("deviation"), digits=4),
                    number(row.get("min"), digits=4),
                    number(row.get("max"), digits=4),
                ]
                for row in report.metrics
            ],
        ),
        "<h2>Not passed</h2>",
        _runs_table(_not_passed(report.runs), report.variants),
        "<h2>All runs</h2>",
        _runs_table(report.runs, report.variants),
        "<h2>Artifacts</h2>",
        table(["run", "kind", "path", "checksum"], _artifact_rows(report.runs)),
        "<h2>Not verified</h2>",
        _notice(report.unverified),
    ]
    return page(
        f"Experiment {experiment.get('uid')}",
        "".join(body),
        generated_at=generated_at,
        standalone=standalone,
    )


def _definition_section(report: TaskReport) -> str:
    """Everything the task is: its prose, its rules, the state it starts from.

    The database keeps the identity of a task and the digest of the snapshot a
    run was worked from; the description, the constraints and the notes live in
    the task directory. When the definition on disk carries a different digest
    than the runs were recorded with, the page says so: an edited task is not
    the task those runs solved, and presenting it as one would be a lie.
    """
    task = report.task
    definition = report.definition
    parts = ["<h2>What the task asks</h2>"]
    if definition is None:
        parts.append(
            '<p class="muted">the task definition is not available to this report; '
            "write the report from a checkout that holds the dataset directory to "
            "see the description, the constraints and the notes</p>"
        )
    else:
        if definition.get("title"):
            parts.append(f'<p class="task-title">{esc(definition["title"])}</p>')
        if definition.get("description"):
            parts.append(f'<p class="task-description">{esc(definition["description"])}</p>')
        if definition.get("description_markdown"):
            parts.append(
                '<details open><summary>full description (markdown source)</summary>'
                f"<pre class='prose'>{esc(definition['description_markdown'])}</pre></details>"
            )
        if definition.get("constraints"):
            parts.append("<h3>Constraints</h3><ul class='constraints'>")
            parts += [f"<li>{esc(item)}</li>" for item in definition["constraints"]]
            parts.append("</ul>")
        if definition.get("notes"):
            parts.append(f'<h3>Notes</h3><p class="task-notes">{esc(definition["notes"])}</p>')

    parts.append("<h3>Recorded identity</h3>")
    parts.append(
        table(
            ["field", "value"],
            [
                ["uid", esc(task.get("uid"))],
                ["category", esc(task.get("category"))],
                ["difficulty", esc(task.get("difficulty"))],
                ["evaluator", esc(task.get("evaluator"))],
                ["base commit", esc(task.get("base_commit"))],
                ["repository", esc(task.get("repository_uid"))],
                ["snapshot digest", f'<code>{esc(task.get("snapshot_digest"))}</code>'],
            ]
            + (
                [
                    ["source", esc(definition.get("repository"))],
                    ["ref", esc(definition.get("ref"))],
                    ["mutation", esc(definition.get("mutation") or "none")],
                    [
                        "timeout",
                        number(definition.get("timeout_seconds")) + " s"
                        if definition.get("timeout_seconds") is not None
                        else NOT_MEASURED,
                    ],
                    ["hidden tests", esc(definition.get("hidden_tests"))],
                    ["public tests", esc(definition.get("public_tests"))],
                    ["definition digest", f'<code>{esc(definition.get("digest"))}</code>'],
                    ["definition path", esc(definition.get("path"))],
                ]
                if definition
                else []
            ),
        )
    )
    if definition is not None:
        recorded = task.get("snapshot_digest")
        if recorded and definition.get("digest") and recorded != definition["digest"]:
            parts.append(
                '<div class="notice"><strong>The definition on disk is not the one these '
                "runs were worked from.</strong> The recorded snapshot digest and the digest "
                "of the task directory differ; what is printed above is the current "
                "definition, and it may not be what the runs below were given.</div>"
            )
    return "".join(parts)


def render_task(report: TaskReport, *, generated_at: str | None = None) -> str:
    task = report.task
    summary = report.summary
    body = [
        "<h1>Task</h1>",
        f'<p class="subtitle">{esc(task.get("uid"))}</p>',
        cards(
            [
                ("runs", number(summary.get("runs"))),
                ("success rate", percent(summary.get("success_rate"))),
                ("mean time", duration(summary.get("mean_duration_seconds"))),
                ("tokens", number(summary.get("total_tokens"))),
            ]
        ),
        _definition_section(report),
        "<h2>Runs of this task</h2>",
        "<p class='muted'>in the order they started; the parameters column is the "
        "configuration each run was executed under</p>",
        _runs_table(report.runs, report.variants, show_task=False),
        "<h2>Not verified</h2>",
        _notice(report.unverified),
    ]
    return page(f"Task {task.get('uid')}", "".join(body), generated_at=generated_at)


def _values(values: Any) -> str:
    if not values:
        return '<span class="muted">(reference)</span>'
    if isinstance(values, dict):
        return esc(", ".join(f"{key}={value}" for key, value in sorted(values.items())))
    return esc(values)


def slugify(value: str) -> str:
    """A filesystem-safe, readable directory name for a subject label.

    Labels carry what an agent or a router called itself, slashes and spaces
    included (``qwen/Qwen3.8-27B``), and a directory per subject has to survive
    that without nesting pages one level deeper than the tree expects.
    """
    slug = re.sub(r"[^a-zA-Z0-9.]+", "-", str(value)).strip("-.").lower()
    return slug or "unnamed"


def render_subject(report: SubjectReport, *, generated_at: str | None = None) -> str:
    """Every run of one agent, runtime, plugin or model, with its parameters."""
    summary = report.summary
    title = f"{report.kind} {report.label}"
    body = [
        "<h1>" + esc(report.kind) + "</h1>",
        f'<p class="subtitle">{esc(report.label)}</p>',
        cards(
            [
                ("runs", number(summary.get("runs"))),
                ("evaluated", number(summary.get("evaluated"))),
                ("success rate", percent(summary.get("success_rate"))),
                ("mean time", duration(summary.get("mean_duration_seconds"))),
                ("tokens", number(summary.get("total_tokens"))),
            ]
        ),
    ]
    if report.experiments:
        body.append("<h2>Experiments this subject took part in</h2>")
        body.append(
            table(
                ["experiment", "title", "type", "runs #", "evaluated #", "passed #",
                 "success rate", "mean time", "tokens #"],
                [
                    [
                        _experiment_link(row.get("uid")),
                        esc(row.get("title")),
                        esc(row.get("type")),
                        number(row.get("runs") or 0),
                        number(row.get("evaluated") or 0),
                        number(row.get("passed") or 0),
                        percent(row.get("success_rate")),
                        duration(row.get("mean_duration_seconds")),
                        number(row.get("total_tokens")),
                    ]
                    for row in report.experiments
                ],
            )
        )
    if report.tasks:
        body.append("<h2>Tasks this subject worked</h2>")
        body.append(
            table(
                ["task", "category", "difficulty", "runs #", "passed #", "success rate",
                 "mean time", "tokens #"],
                [
                    [
                        f'<a href="{ROOT_TOKEN}tasks/{esc(row.get("uid"))}/index.html">'
                        f"{esc(row.get('uid'))}</a>",
                        esc(row.get("category")),
                        esc(row.get("difficulty")),
                        number(row.get("runs") or 0),
                        number(row.get("passed") or 0),
                        percent(row.get("success_rate")),
                        duration(row.get("mean_duration_seconds")),
                        number(row.get("total_tokens")),
                    ]
                    for row in report.tasks
                ],
            )
        )
    if report.observations:
        body.append(f"<h2>{esc(report.kind)} observations</h2>")
        if report.kind == "plugin":
            body.append(
                table(
                    ["run", "version", "enabled", "verification", "note"],
                    [
                        [
                            _run_link({"uid": row.get("run_uid")}),
                            esc(row.get("plugin_version")),
                            "yes" if row.get("enabled") else "no",
                            f'<span class="badge {_badge_css(row.get("verification_status"))}">'
                            f"{esc(row.get('verification_status'))}</span>",
                            _note_cell(row.get("note")),
                        ]
                        for row in report.observations
                    ],
                )
            )
        else:
            body.append(
                table(
                    ["run", "requested", "observed", "source", "verification"],
                    [
                        [
                            _run_link({"uid": row.get("run_uid")}),
                            esc(row.get("requested_model")),
                            esc(row.get("observed_model")),
                            esc(row.get("value_source")),
                            f'<span class="badge {_badge_css(row.get("verification_status"))}">'
                            f"{esc(row.get('verification_status'))}</span>",
                        ]
                        for row in report.observations
                    ],
                )
            )
    body.append("<h2>Runs</h2>")
    body.append(
        "<p class='muted'>in the order they started; the parameters column is the "
        "configuration each run was executed under</p>"
    )
    body.append(
        _runs_table(
            report.runs,
            report.variants,
            show_task=report.kind != "task",
            show_agent=report.kind != "agent",
        )
    )
    body.append("<h2>Not verified</h2>")
    body.append(_notice(report.unverified))
    return page(title, "".join(body), generated_at=generated_at)


def _badge_css(status: Any) -> str:
    return "pass" if status == "verified" else "warn"


def _group_by(runs: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        value = run.get(key)
        groups.setdefault(str(value) if value is not None else "(none)", []).append(run)
    return groups


def render_listing(
    title: str, subtitle: str, rows: list[list[str]], headers: list[str]
) -> str:
    body = f"<h1>{esc(title)}</h1><p class='subtitle'>{esc(subtitle)}</p>" + table(headers, rows)
    return page(title, body)


def asset_names() -> tuple[str, ...]:
    return ASSET_NAMES


def write_report_tree(
    root: Path | str,
    data: HistoryData,
    *,
    generated_at: str | None = None,
    dataset: Any = None,
) -> list[Path]:
    """Write the report tree under ``root``; returns every file written.

    ``dataset`` is the dataset the tasks came from. It is optional: a report of
    a database on its own loses the task prose, says so on each task page, and
    stays correct about everything else.
    """
    root = Path(root)
    written: list[Path] = []

    def write(relative: str, document: str) -> None:
        """Write one page, resolving the css and navigation prefixes for its path.

        The depth is read back from the path being written rather than passed
        in: an experiment uid may contain a slash (an ad-hoc run is recorded
        under ``adhoc/<agent>``), which nests the page one level deeper, and a
        prefix that is one ``../`` short leaves that page rendering without its
        stylesheet.
        """
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        depth = len(PurePosixPath(relative).parent.parts)
        prefix = "../" * depth
        rendered = document.replace(CSS_TOKEN, f"{prefix}{STYLE_NAME}").replace(
            ROOT_TOKEN, prefix
        )
        target.write_text(rendered, encoding="utf-8")
        written.append(target)

    stylesheet = root / STYLE_NAME
    stylesheet.parent.mkdir(parents=True, exist_ok=True)
    stylesheet.write_text(STYLE, encoding="utf-8")
    written.append(stylesheet)

    write("index.html", render_index(data, generated_at=generated_at))
    for experiment in data.experiments:
        uid = str(experiment["uid"])
        write(
            f"experiments/{uid}/index.html",
            render_experiment(build_experiment_report(data, uid), generated_at=generated_at),
        )
    for task in data.tasks:
        uid = str(task["uid"])
        write(
            f"tasks/{uid}/index.html",
            render_task(
                build_task_report(data, uid, dataset=dataset), generated_at=generated_at
            ),
        )

    stats = dashboard(data)
    write("tasks/index.html", _task_listing(data))
    write(
        "agents/index.html",
        _group_listing(
            "Agents",
            "one row per agent identity; a row opens the runs of that agent",
            stats["agents"],
            "agent",
        ),
    )
    write(
        "runtimes/index.html",
        _group_listing(
            "Runtimes",
            "one row per runtime; a row opens the runs of that runtime",
            stats["runtimes"],
            "runtime",
        ),
    )
    write("plugins/index.html", _plugin_listing(stats["plugins"]))
    write("models/index.html", _model_listing(stats["models"]))
    write("categories/index.html", _subject_listing("Categories", data, "category"))
    write("difficulties/index.html", _subject_listing("Difficulties", data, "difficulty"))
    write("verdicts/index.html", _verdict_listing(data))
    write(
        f"{RUNS_DIRECTORY}/index.html",
        render_listing(
            "Runs",
            "every recorded run, newest first",
            _run_rows(order_by_start(data.runs)[::-1], _all_variants(data)),
            _runs_headers(),
        ),
    )

    for run in data.runs:
        uid = str(run["uid"])
        report = build_run_report(data, uid, dataset=dataset)
        if report is not None:
            write(
                f"{RUNS_DIRECTORY}/{uid}/index.html",
                render_run(report, generated_at=generated_at),
            )

    for stats_key, stats_field, kind, directory in (
        ("by_category", "category", "category", "categories"),
        ("by_difficulty", "difficulty", "difficulty", "difficulties"),
    ):
        builders = {"category": build_category_report, "difficulty": build_difficulty_report}
        for row in stats[stats_key]:
            label = str(row.get(stats_field))
            write(
                f"{directory}/{slugify(label)}/index.html",
                render_subject(
                    builders[kind](data, label), generated_at=generated_at
                ),
            )
    for verdict in sorted(stats["verdicts"]):
        write(
            f"verdicts/{slugify(verdict)}/index.html",
            render_subject(build_verdict_report(data, verdict), generated_at=generated_at),
        )

    for row in stats["agents"]:
        label = str(row.get("agent"))
        write(
            f"agents/{slugify(label)}/index.html",
            render_subject(
                build_agent_report(data, label), generated_at=generated_at
            ),
        )
    for row in stats["runtimes"]:
        label = str(row.get("runtime"))
        write(
            f"runtimes/{slugify(label)}/index.html",
            render_subject(
                build_runtime_report(data, label), generated_at=generated_at
            ),
        )
    for row in stats["plugins"]:
        label = str(row.get("plugin"))
        write(
            f"plugins/{slugify(label)}/index.html",
            render_subject(
                build_plugin_report(data, label), generated_at=generated_at
            ),
        )
    for row in stats["models"]:
        label = str(row.get("requested"))
        write(
            f"models/{slugify(label)}/index.html",
            render_subject(
                build_model_report(data, label), generated_at=generated_at
            ),
        )
    return written


def _task_listing(data: HistoryData) -> str:
    rows = [
        [
            f'<a href="{esc(row["uid"])}/index.html">{esc(row["uid"])}</a>',
            esc(row.get("category")),
            esc(row.get("difficulty")),
            esc(row.get("evaluator")),
            number(row.get("runs") or 0),
        ]
        for row in data.tasks
    ]
    return render_listing(
        "Tasks",
        "every recorded task",
        rows,
        ["task", "category", "difficulty", "evaluator", "runs #"],
    )


def _group_listing(title: str, subtitle: str, rows: list[dict[str, Any]], label: str) -> str:
    return render_listing(
        title,
        subtitle,
        [
            [
                esc(row.get(label)),
                number(row.get("runs") or 0),
                number(row.get("evaluated") or 0),
                number(row.get("passed") or 0),
                percent(row.get("success_rate")),
                duration(row.get("mean_duration_seconds")),
                number(row.get("total_tokens")),
                esc(", ".join(row.get("statuses") or [])),
            ]
            for row in rows
        ],
        [
            label,
            "runs #",
            "evaluated #",
            "passed #",
            "success rate",
            "mean time",
            "tokens #",
            "statuses",
        ],
    )


def _plugin_listing(rows: list[dict[str, Any]]) -> str:
    return render_listing(
        "Plugins",
        "what the history says about each plugin",
        [
            [
                f'<a href="{esc(slugify(str(row.get("plugin"))))}/index.html">'
                f"{esc(row.get('plugin'))}</a>",
                number(row.get("runs") or 0),
                number(row.get("enabled_runs") or 0),
                esc(", ".join(row.get("versions") or []) or NOT_MEASURED),
                _badges(row.get("verification_statuses") or {}),
                "yes" if row.get("verified") else "no",
            ]
            for row in rows
        ],
        ["plugin", "runs #", "enabled runs #", "versions", "verification", "all verified"],
    )


def _model_listing(rows: list[dict[str, Any]]) -> str:
    return render_listing(
        "Models",
        "requested versus observed model, with the trust the observed value deserves",
        [
            [
                f'<a href="{esc(slugify(str(row.get("requested"))))}/index.html">'
                f"{esc(row.get('requested'))}</a>",
                esc(row.get("observed")),
                number(row.get("runs") or 0),
                esc(", ".join(row.get("sources") or []) or NOT_MEASURED),
                _badges(row.get("verification_statuses") or {}),
            ]
            for row in rows
        ],
        ["requested", "observed", "runs #", "source", "verification"],
    )


def experiment_unverified(data: HistoryData, uid: str) -> list[dict[str, Any]]:
    """Exposed for tests: the unverified findings of one experiment."""
    return unverified_configurations(
        HistoryData(
            experiments=[row for row in data.experiments if row.get("uid") == uid],
            plugins=[
                row
                for row in data.plugins
                if row.get("run_uid")
                in {run.get("uid") for run in data.runs_for_experiment(uid)}
            ],
            models=[
                row
                for row in data.models
                if row.get("run_uid")
                in {run.get("uid") for run in data.runs_for_experiment(uid)}
            ],
        )
    )
