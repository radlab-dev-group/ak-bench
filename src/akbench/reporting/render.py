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
    VariantReport,
    build_agent_report,
    build_category_report,
    build_difficulty_report,
    build_experiment_report,
    build_model_report,
    build_plugin_report,
    build_run_report,
    build_runtime_report,
    build_task_report,
    build_variant_report,
    build_verdict_report,
    configuration_ranking,
    dashboard,
    duration_seconds,
    order_by_start,
    unverified_configurations,
    variant_lookup,
    verdict_of,
)
from akbench.reporting.docs import (
    Document,
    discover_documents,
    group_of,
    group_order,
    page_paths,
)

STYLE_NAME = "assets/style.css"
ASSET_NAMES: tuple[str, ...] = (STYLE_NAME,)
NOT_MEASURED = "not measured"
CSS_TOKEN = "{{css}}"
ROOT_TOKEN = "{{root}}"

STYLE = """
/* AK-Bench report — a benchmark dashboard, built for comparing numbers.

   The page is a dark, neutral slate with one cool accent, because a report of
   this kind is read as a leaderboard: the eye goes to the place, the success
   rate and the bar, and everything else stays quiet until it is looked for.
   Prose and labels are set in a humanist sans; every identifier and every
   measurement is monospaced with tabular figures, so a column of numbers
   lines up and a hash does not pretend to be a word. Nothing here flatters a
   value: a bar is drawn to scale, a missing value says so in words, and a
   failed run is coloured, never hidden. Print falls back to a light scheme. */
:root {
  --bg: #0b1017; --panel: #10161f; --raise: #151d28; --head: #131b26;
  --fg: #d7dee8; --bright: #f6f8fb; --muted: #8a97a8; --faint: #5d6a7b;
  --line: #243040; --line-soft: #1b2531;
  --accent: #5eb1ff; --accent-soft: rgba(94, 177, 255, .14);
  --pass: #3ecf8e; --fail: #ff6b7a; --warn: #f3b63f;
  --gold: #f5c451; --silver: #c3ccd8; --bronze: #d29a6a;
  --row: rgba(255, 255, 255, .025);
  --sans: "Inter", "SF Pro Text", ui-sans-serif, system-ui, "Segoe UI", Roboto,
          "Helvetica Neue", Arial, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  /* the page grows with the window. A run table is fourteen columns of
     numbers, so the width a report needs is set by its widest table, not by
     a book measure; the cap exists only so an ultrawide monitor does not
     scatter a row of numbers across a metre of glass. */
  --page-min: 22rem; --page-max: 168rem;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
* { scrollbar-color: var(--line) var(--bg); }
*::-webkit-scrollbar { height: 10px; width: 10px; }
*::-webkit-scrollbar-track { background: var(--bg); }
*::-webkit-scrollbar-thumb { background: var(--line); border-radius: 5px;
  border: 2px solid var(--bg); }
*::-webkit-scrollbar-thumb:hover { background: var(--muted); }
body {
  margin: 0; padding: 0 clamp(.75rem, 1.6vw, 2rem) 4rem;
  background:
    radial-gradient(1200px 420px at 50% -200px, rgba(94, 177, 255, .10), transparent 70%),
    var(--bg);
  color: var(--fg); font: 15px/1.6 var(--sans);
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
main {
  width: min(100%, var(--page-max)); min-width: min(100%, var(--page-min));
  margin: 1.4rem auto 0; padding: 0 clamp(1rem, 2vw, 2.4rem) 2.2rem;
  border: 1px solid var(--line); border-radius: 12px; background: var(--panel);
  box-shadow: 0 20px 60px rgba(0, 0, 0, .35);
}
/* the top bar: the brand on the left, the sections on the right. It is the
   one piece of chrome a page carries, and it is the same on every page. */
.topbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: .6rem 1.4rem;
  margin: 0 calc(-1 * clamp(1rem, 2vw, 2.4rem)) 1.8rem;
  padding: .85rem clamp(1rem, 2vw, 2.4rem);
  border-bottom: 1px solid var(--line); background: var(--head);
  border-radius: 12px 12px 0 0;
}
.brand {
  display: inline-flex; align-items: center; gap: .55rem; color: var(--bright);
  font-weight: 700; letter-spacing: .02em; font-size: .95rem; border: none;
}
.brand:hover { color: var(--bright); border: none; }
.brand .mark {
  width: 1.35rem; height: 1.35rem; border-radius: 6px;
  background: linear-gradient(135deg, var(--accent), #8f7bff);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, .08) inset;
}
.brand .tag {
  color: var(--muted); font-weight: 500; font-size: .74rem; letter-spacing: .1em;
  text-transform: uppercase; margin-left: .35rem;
}
.nav { display: flex; flex-wrap: wrap; gap: .25rem; margin-left: auto; font-size: .82rem; }
.nav a {
  color: var(--muted); padding: .3rem .7rem; border-radius: 6px; border: none;
  font-weight: 500;
}
.nav a:hover { color: var(--bright); background: var(--accent-soft); border: none; }
h1 {
  font-size: 1.55rem; margin: 0 0 .3rem; letter-spacing: -.01em; font-weight: 700;
  color: var(--bright);
}
h2 {
  display: flex; align-items: center; gap: .6rem;
  font-size: .78rem; margin: 2.6rem 0 .9rem; letter-spacing: .12em; text-transform: uppercase;
  color: var(--muted); font-weight: 600;
}
h2::before { content: ""; width: 3px; height: 1em; border-radius: 2px; background: var(--accent); }
h2::after { content: ""; flex: 1; height: 1px; background: var(--line-soft); }
h3 {
  font-size: .74rem; margin: 1.5rem 0 .5rem; letter-spacing: .1em; text-transform: uppercase;
  color: var(--muted); font-weight: 600;
}
a { color: var(--accent); text-decoration: none; border-bottom: 1px solid transparent; }
a:hover { color: var(--bright); border-bottom-color: var(--accent); }
.subtitle { color: var(--muted); margin: 0 0 1.5rem; font-size: .92rem; }
/* identifiers and measurements are monospaced; a table is mostly that, so the
   whole table takes the mono face and the headers take the sans */
.subtitle, td, .card .value, .who, code, .badge, .place, .task-title { font-family: var(--mono); }
/* A run table is wide by nature. It is laid out to fit the page: the number
   columns hug their content, the text columns take what is left and wrap, and
   the type tightens as columns are added (class dense at ten columns, x-dense
   at thirteen). Horizontal scroll stays as the fallback for a narrow window,
   not as the normal way to read a row. */
.table-wrap {
  overflow-x: auto; margin: .6rem 0 1.3rem; border: 1px solid var(--line);
  border-radius: 10px; background: var(--raise);
}
table { border-collapse: separate; border-spacing: 0; width: 100%; font-size: .84rem; }
th, td {
  border-bottom: 1px solid var(--line-soft); padding: .6rem .8rem;
  text-align: left; vertical-align: top; font-variant-numeric: tabular-nums;
}
tbody tr:last-child td { border-bottom: none; }
th {
  position: sticky; top: 0; z-index: 1; background: var(--head); color: var(--muted);
  font: 600 .7rem/1.4 var(--sans); letter-spacing: .08em; text-transform: uppercase;
  border-bottom: 1px solid var(--line); white-space: nowrap;
}
th.sortable { cursor: pointer; user-select: none; }
th.sortable::after { content: " \\2195"; color: var(--faint); }
th.sortable:hover { color: var(--bright); background: var(--accent-soft); }
th.sortable:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
th[aria-sort="ascending"], th[aria-sort="descending"] { color: var(--bright); }
th[aria-sort="ascending"]::after { content: " \\2191"; color: var(--accent); }
th[aria-sort="descending"]::after { content: " \\2193"; color: var(--accent); }
tbody tr:nth-child(even) { background: var(--row); }
tbody tr { transition: background .08s ease; }
tbody tr:hover { background: var(--accent-soft); }
td.num, th.num { text-align: right; }
/* the density classes: written by table() from the column count, so a table of
   four columns keeps its comfortable size and a table of fourteen fits the page */
table.dense { font-size: .78rem; }
table.dense th, table.dense td { padding: .45rem .55rem; }
table.dense th { white-space: normal; }
table.dense td { overflow-wrap: anywhere; }
table.dense td.num, table.dense th.num { width: 1%; white-space: nowrap; }
table.dense .cell { min-width: 4.4rem; }
table.x-dense { font-size: .72rem; }
table.x-dense th, table.x-dense td { padding: .38rem .45rem; }
table.x-dense th { letter-spacing: .05em; }
table.x-dense .cell { min-width: 3.8rem; }
table.x-dense .bar { height: .5rem; }
/* a text cell keeps a floor. A column that can be squeezed to three
   characters is a column read by scrolling back and forth, which is what the
   wider page exists to avoid; below the floor the wrapper scrolls instead. */
td { overflow-wrap: anywhere; }
table.dense td:not(.num) { min-width: 6.2rem; }
table.x-dense td:not(.num) { min-width: 5.6rem; }
/* the headline figures: one card per measure, the value large, the label small */
.cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
  gap: .75rem; margin: 1.2rem 0 1.9rem;
}
.card {
  position: relative; overflow: hidden; border: 1px solid var(--line); border-radius: 10px;
  padding: .85rem 1rem .9rem; background: linear-gradient(180deg, var(--raise), var(--panel));
}
.card::before {
  content: ""; position: absolute; inset: 0 0 auto 0; height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
  opacity: .7;
}
.card .label {
  color: var(--muted); font-size: .68rem; letter-spacing: .1em; text-transform: uppercase;
  font-weight: 600; margin-bottom: .35rem;
}
.card .value {
  font-size: 1.5rem; color: var(--bright); line-height: 1.2; font-weight: 600;
  font-variant-numeric: tabular-nums; overflow-wrap: anywhere;
}
.card .value .muted { font-size: .95rem; font-weight: 500; }
.pass { color: var(--pass); }
.fail { color: var(--fail); }
.warn { color: var(--warn); }
.muted { color: var(--muted); }
/* a verdict in a cell or a card reads as a pill, so a column of them scans */
td > .pass, td > .fail, .card .value > .pass, .card .value > .fail {
  display: inline-block; padding: .08rem .55rem; border-radius: 999px; font-size: .9em;
  font-weight: 600; border: 1px solid currentColor; background: rgba(0, 0, 0, .2);
}
.card .value > .pass, .card .value > .fail { font-size: 1.05rem; padding: .2rem .8rem; }
/* a value that is one token (a hash, a time window) must not fold in the
   middle of itself; folding it would make the cell taller and harder to read */
.nowrap { white-space: nowrap; }
.badge {
  display: inline-block; border: 1px solid var(--line); border-radius: 999px;
  padding: .06rem .55rem; font-size: .68rem; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); white-space: nowrap; background: var(--raise);
}
.badge.warn { border-color: rgba(243, 182, 63, .5); color: var(--warn);
  background: rgba(243, 182, 63, .08); }
.badge.pass { border-color: rgba(62, 207, 142, .5); color: var(--pass);
  background: rgba(62, 207, 142, .08); }
.notice {
  border: 1px solid rgba(243, 182, 63, .35); border-left: 3px solid var(--warn);
  background: rgba(243, 182, 63, .07);
  padding: .8rem 1rem; margin: 1rem 0; font-size: .88rem; border-radius: 8px;
}
code {
  font: .82rem/1.5 var(--mono); word-break: break-all; color: var(--bright);
  background: rgba(0, 0, 0, .3); border: 1px solid var(--line-soft); border-radius: 4px;
  padding: .05rem .3rem;
}
.note { color: var(--muted); font-size: .82rem; margin: -.4rem 0 1.2rem; }
.task-title { color: var(--bright); font-size: 1.05rem; margin: 0 0 .5rem; font-weight: 600; }
/* prose is the one thing that should not stretch: a task description stays at
   a measure that can be read across without tracking a line back */
.task-description, .task-notes { max-width: 80rem; }
pre.prose {
  max-width: 80rem; margin: .4rem 0 1rem; padding: .95rem 1.1rem; white-space: pre-wrap;
  overflow-wrap: anywhere; background: var(--raise); border: 1px solid var(--line);
  border-left: 3px solid var(--accent); border-radius: 8px; font: .84rem/1.6 var(--mono);
  color: var(--fg);
}
details { margin: .5rem 0 1.1rem; }
summary { cursor: pointer; color: var(--muted); font-size: .78rem; letter-spacing: .08em;
  text-transform: uppercase; font-weight: 600; }
summary:hover { color: var(--bright); }
ul.constraints { max-width: 80rem; margin: .3rem 0 1rem; padding-left: 1.2rem; }
ul.constraints li { margin: .15rem 0; }
.folded { cursor: help; border-bottom: 1px dotted var(--muted); }
footer {
  margin-top: 2.8rem; color: var(--faint); font-size: .76rem; letter-spacing: .04em;
  border-top: 1px solid var(--line); padding-top: .9rem;
}
/* the ranking: a place is a medal in a ring, and the first three are coloured
   the way a podium is. The bars beside it are a measurement drawn to scale,
   never decoration. */
.place {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 1.9rem; height: 1.9rem; padding: 0 .4rem; border-radius: 999px;
  font-size: .9rem; font-weight: 700; color: var(--muted);
  border: 1px solid var(--line); background: var(--raise);
}
.place.top {
  color: #1a1304; background: linear-gradient(160deg, #ffe08a, var(--gold));
  border-color: transparent; box-shadow: 0 0 0 3px rgba(245, 196, 81, .18);
}
tbody tr:nth-child(2) .place:not(.top) {
  color: #141a22; background: linear-gradient(160deg, #e6ecf3, var(--silver));
  border-color: transparent;
}
tbody tr:nth-child(3) .place:not(.top) {
  color: #1d1208; background: linear-gradient(160deg, #e9b98f, var(--bronze));
  border-color: transparent;
}
.bars { display: grid; gap: .5rem; margin: .5rem 0 1.3rem; }
.bar-row {
  display: grid; grid-template-columns: minmax(9rem, 22rem) 1fr; gap: .8rem;
  align-items: center; font-size: .82rem;
}
.bar-row .who { color: var(--fg); overflow-wrap: anywhere; }
.bar {
  position: relative; height: .7rem; background: rgba(0, 0, 0, .35);
  border: 1px solid var(--line-soft); min-width: 6rem; border-radius: 999px; overflow: hidden;
}
.bar > span {
  position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px;
  background: linear-gradient(90deg, #3b8fe6, var(--accent));
}
.bar.cost > span { background: linear-gradient(90deg, #c98c1d, var(--warn)); }
.bar-note { color: var(--muted); font-size: .78rem; margin: -.5rem 0 1.3rem; }
.cell .bar { margin-top: .35rem; }
.cell { min-width: 5.5rem; }
/* the documentation tree: a menu that stays beside the text it belongs to and
   a body that reads like a document, not like a table. The prose keeps the
   heading rhythm of the source file — a document has to read the same here as
   it does in the editor — while every measurement on the rest of the report
   stays as compact as a table needs. */
.docs-layout {
  display: grid; grid-template-columns: minmax(14rem, 19rem) minmax(0, 1fr);
  gap: clamp(1.2rem, 2.5vw, 2.4rem); align-items: start;
}
.docs-menu {
  position: sticky; top: 1rem; max-height: calc(100vh - 2rem); overflow: auto;
  border: 1px solid var(--line); border-radius: 10px; background: var(--raise);
  padding: .9rem 1rem 1.1rem; font-size: .82rem;
}
.docs-menu .menu-group { margin: 0 0 1rem; }
.docs-menu .menu-group:last-child { margin-bottom: 0; }
.docs-menu .menu-title {
  color: var(--faint); font: 600 .68rem/1.4 var(--sans); letter-spacing: .12em;
  text-transform: uppercase; margin: 0 0 .35rem;
}
.docs-menu ul { list-style: none; margin: 0; padding: 0; display: grid; gap: .12rem; }
.docs-menu a { display: block; color: var(--muted); padding: .2rem .45rem; border-radius: 6px; }
.docs-menu a:hover { color: var(--bright); background: var(--accent-soft); border: none; }
.docs-menu a.current { color: var(--bright); background: var(--accent-soft); font-weight: 600; }
.docs-menu .toc { margin: .3rem 0 .1rem .55rem; display: grid; gap: .05rem; }
.docs-menu .toc a { font-size: .76rem; padding: .1rem .4rem; }
.prose { min-width: 0; }
/* the document's own heading scale: the report's uppercase labels measure a
   table, a document measures a page */
.prose h1, .prose h2, .prose h3, .prose h4 {
  display: block; letter-spacing: -.01em; text-transform: none; color: var(--bright);
  font-weight: 700; line-height: 1.3;
}
.prose h1 { font-size: 1.55rem; margin: 0 0 .6rem; }
.prose h2 { font-size: 1.12rem; margin: 2.2rem 0 .7rem; padding-bottom: .3rem;
  border-bottom: 1px solid var(--line-soft); }
.prose h3 { font-size: .98rem; margin: 1.7rem 0 .5rem; }
.prose h4 { font-size: .9rem; margin: 1.4rem 0 .4rem; color: var(--fg); }
.prose h2::before, .prose h2::after { content: none; }
.prose p, .prose li { font-size: .92rem; line-height: 1.65; }
.prose p { margin: .7rem 0; }
.prose ul, .prose ol { margin: .7rem 0 1rem; padding-left: 1.35rem; }
.prose li { margin: .22rem 0; }
.prose li > ul, .prose li > ol { margin: .2rem 0; }
.prose code {
  background: rgba(94, 177, 255, .1); border: 1px solid var(--line-soft);
  border-radius: 4px; padding: .05rem .3rem; font-size: .85em;
}
.prose .code-block { position: relative; margin: .9rem 0 1.2rem; }
.prose .code-block pre {
  margin: 0; padding: .9rem 1rem; overflow-x: auto; border: 1px solid var(--line);
  border-radius: 10px; background: var(--head); font: .8rem/1.6 var(--mono);
}
.prose .code-block code { background: none; border: none; padding: 0; }
.prose .code-lang {
  position: absolute; top: .35rem; right: .7rem; color: var(--faint);
  font: 600 .64rem/1 var(--sans); letter-spacing: .1em; text-transform: uppercase;
}
.prose blockquote {
  margin: .9rem 0; padding: .1rem 0 .1rem .95rem; border-left: 2px solid var(--accent);
  color: var(--muted);
}
.prose blockquote p { margin: .35rem 0; }
.prose hr { border: none; border-top: 1px solid var(--line); margin: 1.8rem 0; }
.prose .table-wrap table { font-size: .82rem; }
.prose .table-wrap td { overflow-wrap: anywhere; }
@media (max-width: 60rem) {
  .docs-layout { grid-template-columns: 1fr; }
  .docs-menu { position: static; max-height: none; }
}
@media print {
  .docs-menu { display: none; }
  .docs-layout { grid-template-columns: 1fr; }
  .prose .code-block pre { white-space: pre-wrap; }
}
@media (max-width: 40rem) {
  .topbar { gap: .5rem; }
  .nav { margin-left: 0; }
  h1 { font-size: 1.3rem; }
}
@media print {
  .bar { border-color: #999; background: #f2f2f2; }
  .bar > span { background: #0b5cad; }
  .bar.cost > span { background: #8a6100; }
  :root { --bg: #fff; --panel: #fff; --raise: #fafafa; --fg: #14171a; --bright: #000;
          --muted: #565c63; --faint: #777; --line: #c2c8cc; --line-soft: #e2e6e8; --head: #f0f2f3;
          --accent: #0b5cad; --accent-soft: #eef4fb; --pass: #0a7d38; --warn: #8a6100;
          --fail: #b3261e; --row: #f7f8f9; }
  body { font-size: 11px; background: #fff; }
  main { border: none; padding: 0; box-shadow: none; }
  .topbar { background: none; border-radius: 0; margin: 0 0 1rem; padding: 0 0 .6rem; }
  th { position: static; }
  .place.top, tbody tr:nth-child(2) .place, tbody tr:nth-child(3) .place { box-shadow: none; }
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
      // the direction that was applied is remembered on the header, because
      // the next click has to flip it: without this every click sorts the same
      // way, which is the bug this line exists to prevent
      if (i === index) {
        cells[i].setAttribute("data-dir", ascending ? "asc" : "desc");
        cells[i].setAttribute(
          "aria-sort",
          ascending ? "ascending" : "descending"
        );
      } else {
        cells[i].removeAttribute("data-dir");
        cells[i].setAttribute("aria-sort", "none");
      }
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
    """A table; a header ending in ``#`` is right-aligned as a number.

    The table is marked with a density class from its own column count, so the
    stylesheet can tighten the type exactly when a row of numbers would else
    overflow the page.
    """
    if not headers or not rows:
        return '<p class="muted">nothing recorded</p>'

    classes = _density_classes(len(headers))

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
        f'<div class="table-wrap"><table{classes}><thead><tr>'
        f"{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _density_classes(columns: int) -> str:
    """The density attribute for a table of ``columns`` columns."""
    if columns >= 13:
        return ' class="dense x-dense"'
    if columns >= 10:
        return ' class="dense"'
    return ""


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
    # the top bar: the brand on every page, and on a page that belongs to a
    # tree the sections of that tree. A standalone export has no tree to link
    # into, so it carries the brand alone.
    brand = (
        '<span class="mark"></span>AK-Bench<span class="tag">benchmark report</span>'
    )
    if standalone:
        nav = f'<header class="topbar"><span class="brand">{brand}</span></header>'
    else:
        nav = (
            '<header class="topbar">'
            f'<a class="brand" href="{ROOT_TOKEN}index.html">{brand}</a>'
            '<nav class="nav">'
            f'<a href="{ROOT_TOKEN}index.html">dashboard</a>'
            f'<a href="{ROOT_TOKEN}agents/index.html">agents</a>'
            f'<a href="{ROOT_TOKEN}runtimes/index.html">runtimes</a>'
            f'<a href="{ROOT_TOKEN}plugins/index.html">plugins</a>'
            f'<a href="{ROOT_TOKEN}models/index.html">models</a>'
            f'<a href="{ROOT_TOKEN}tasks/index.html">tasks</a>'
            f'<a href="{ROOT_TOKEN}{RUNS_DIRECTORY}/index.html">runs</a>'
            f'<a href="{ROOT_TOKEN}docs/index.html">docs</a>'
            "</nav></header>"
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
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
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
            *TOKEN_HEADERS,
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
                *_token_cells(row),
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


def _chart_labels(rows: list[dict[str, Any]]) -> list[str]:
    """One name per ranking row, for a chart.

    A configuration that was ranked under another agent or another runtime
    appears twice with the same label, so only those rows carry the subject
    that produced them; naming the agent in every other bar would be noise.
    """
    labels = [str(row.get("config") or "") for row in rows]
    duplicated = {label for label in labels if labels.count(label) > 1}
    return [
        f"{label} \u00b7 {row.get('agent')} / {row.get('runtime')}"
        if label in duplicated
        else label
        for label, row in zip(labels, rows, strict=True)
    ]


def _chart(rows: list[dict[str, Any]], key: str, *, css: str = "") -> str:
    """A bar chart of one measure across the ranked configurations."""
    values = [row.get(key) for row in rows]
    measured = [value for value in values if value is not None]
    maximum = max(measured) if measured else None
    labels = _chart_labels(rows)
    parts = [
        '<div class="bar-row"><span class="who">'
        + esc(label)
        + "</span>"
        + _bar(_fraction(row.get(key), maximum), css=css)
        + "</div>"
        for label, row in zip(labels, rows, strict=True)
    ]
    return f'<div class="bars">{"".join(parts)}</div>'


# the columns a cost is read from: what was paid for, what the model produced,
# what the two add up to, and how many times the agent reached for a tool
TOKEN_HEADERS = [
    "input tokens #",
    "generated tokens #",
    "total tokens #",
    "tool calls #",
]


def _token_cells(summary: dict[str, Any]) -> list[str]:
    """The token and tool-call cells of a summarised set of runs."""
    return [
        number(summary.get("input_tokens")),
        number(summary.get("output_tokens")),
        number(summary.get("total_tokens")),
        number(summary.get("tool_calls")),
    ]


# the same cost read per run: a ranking row pools every recording of a
# configuration, and a sum over a different number of runs is not a comparison
MEAN_TOKEN_HEADERS = [
    "mean input tokens #",
    "mean generated tokens #",
    "mean total tokens #",
    "mean tool calls #",
]


def _mean_token_cells(row: dict[str, Any]) -> list[str]:
    """The per-run token and tool-call cells of a pooled ranking row."""
    return [
        number(row.get("mean_input_tokens")),
        number(row.get("mean_output_tokens")),
        number(row.get("mean_total_tokens")),
        number(row.get("mean_tool_calls")),
    ]


def _recording_cell(row: dict[str, Any]) -> str:
    """How many recordings a ranking row pooled, which tasks it rests on and
    when those runs happened.

    A configuration is often recorded more than once — in another recording of
    the same experiment, or in another experiment — and one row now stands for
    all of them, so the row states how many recordings it merged and over what
    window its runs were measured.
    """
    tasks = row.get("task_uids") or []
    if not tasks:
        return '<span class="muted">no run</span>'
    recordings = int(row.get("recordings") or 0)
    started = _short_time(row.get("first_started"))
    finished = _short_time(row.get("last_finished"))
    window = f"{started} &rarr; {finished}" if started and finished else "not recorded"
    shown = ", ".join(str(task).split("@")[0] for task in tasks[:3])
    if len(tasks) > 3:
        shown += f" +{len(tasks) - 3}"
    plural = "recording" if recordings == 1 else "recordings"
    return (
        f'{esc(shown)}<br /><span class="muted nowrap">{recordings} {plural}</span>'
        f'<br /><span class="muted nowrap">{window}</span>'
    )


def _short_time(value: Any) -> str:
    """A timestamp trimmed to what fits a table cell, or an empty string."""
    if not value:
        return ""
    return str(value).replace("T", " ")[:16]


def _shows_subjects(rows: list[dict[str, Any]]) -> bool:
    """Whether a ranking row has to name the agent and runtime it ran under.

    A configuration is keyed by its values, its agent and its runtime, so two
    rows differ by subject only when the ranking holds more than one of them.
    With a single agent on a single runtime the line would repeat the same
    string in every row and say nothing.
    """
    return len({row.get("agent") for row in rows}) > 1 or len(
        {row.get("runtime") for row in rows}
    ) > 1


def _place_cell(row: dict[str, Any]) -> str:
    place = row.get("place")
    if place == 1:
        return f'<span class="place top">{place}</span>'
    return f'<span class="place">{place if place is not None else "&mdash;"}</span>'


def _configuration_cell(row: dict[str, Any], *, subjects: bool) -> str:
    """The configuration a row stands for, with its subject when that decides.

    A baseline badge belongs to the configuration, not to one of its
    recordings, so a configuration is a baseline if any recording of it was
    declared one.
    """
    label = esc(row.get("config"))
    if row.get("is_baseline"):
        label += ' <span class="badge">baseline</span>'
    if subjects:
        label += (
            f'<br /><span class="muted">{esc(row.get("agent"))} &middot; '
            f"{esc(row.get('runtime'))}</span>"
        )
    return label


def _experiments_cell(uids: list[Any]) -> str:
    """The experiments a pooled row came from, the first one linked.

    Naming them all would widen the column for the common case of a single
    experiment; the count of the rest is stated, and the row below it says how
    many recordings those experiments contributed.
    """
    if not uids:
        return '<span class="muted">no experiment</span>'
    shown = _experiment_link(uids[0])
    if len(uids) > 1:
        shown += f'<br /><span class="muted nowrap">+{len(uids) - 1} more</span>'
    return shown


def _ranked_rows(rows: list[dict[str, Any]], *, experiments: bool = False) -> list[list[str]]:
    """The cells of a ranking table, one row per configuration.

    ``experiments`` adds the column naming the experiments the pooled runs came
    from; a page that is already about one experiment has nothing to name.
    """
    subjects = _shows_subjects(rows)
    table_rows: list[list[str]] = []
    for row in rows:
        cells = [_place_cell(row), _configuration_cell(row, subjects=subjects)]
        if experiments:
            cells.append(_experiments_cell(row.get("experiments") or []))
        cells.extend(
            [
                _recording_cell(row),
                number(row.get("runs") or 0),
                number(row.get("evaluated") or 0),
                _cell_bar(percent(row.get("success_rate")), row.get("success_rate")),
                duration(row.get("mean_duration_seconds")),
                *_mean_token_cells(row),
                esc(row.get("vs_baseline") or ""),
            ]
        )
        table_rows.append(cells)
    return table_rows


def _ranking(
    runs: list[dict[str, Any]], variants_by_experiment: dict[str, list[dict[str, Any]]]
) -> str:
    """The place of every configuration, then the same numbers drawn to scale.

    The row of this page pools the variants that carry one configuration — the
    same values run by the same agent on the same runtime — so two recordings
    of an experiment that planned the same values twice become the one row they
    describe, counted over all of their runs.
    """
    rows = configuration_ranking(runs, variants_by_experiment)
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
                "recording",
                "runs #",
                "evaluated #",
                "success rate",
                "mean time",
                *MEAN_TOKEN_HEADERS,
                "against the baseline",
            ],
            _ranked_rows(rows),
        )
        + "<h3>Success rate</h3>"
        + _chart(rows, "success_rate")
        + "<h3>Mean wall-clock time</h3>"
        + _chart(rows, "mean_duration_seconds", css="cost")
        + '<p class="bar-note">each bar is measured against the largest value in its own '
        "column; time and tokens are compared only within this experiment, and a row "
        "is one configuration over all of its recordings. The token and tool-call "
        "columns are means per run, not sums</p>"
    )


def _leaderboard(data: HistoryData) -> str:
    """Every configuration ever recorded, best first: the front-page answer.

    A row is one configuration — the factor values together with the agent and
    the runtime that ran them — and every run of it is pooled into that row,
    whichever experiment or recording it came from. A place is therefore stated
    over the pooled runs of the configuration rather than inside the experiment
    that happened to record it, which is what makes the same configuration in
    two experiments one row instead of two indistinguishable ones.
    """
    rows = configuration_ranking(data.runs, data.variants)
    if not rows:
        return (
            '<p class="muted">nothing recorded yet: a ranking needs runs, and a '
            "place needs an evaluated run. Run an experiment with --store.</p>"
        )
    return (
        table(
            [
                "place",
                "configuration",
                "experiments",
                "recording",
                "runs #",
                "evaluated #",
                "success rate",
                "mean time",
                *MEAN_TOKEN_HEADERS,
                "against the baseline",
            ],
            _ranked_rows(rows, experiments=True),
        )
        + '<p class="bar-note">one row is one configuration: its factor values with the '
        "agent and the runtime that ran them. Every run of that configuration is pooled "
        "into the row, from however many experiments and recordings it came, and its "
        "place is stated over the pooled runs &mdash; recordings need not share a task "
        "set, a model or a day, which the *experiments* and *recording* columns state. "
        "Tokens and tool calls are means per run, because a sum over a different number "
        "of runs is not comparable; &mdash; means nothing was evaluated, which is not "
        "the same as failing</p>"
    )


def variant_page_path(experiment_uid: Any, variant_uid: Any) -> str:
    """Where the page of one variant lives, relative to the root of the tree.

    A variant uid is unique inside its experiment and says nothing outside it,
    so the page of one hangs under the experiment that planned it. The same
    relative path is used by the writer and by every link, because a variant
    page is linked from the experiment page two directories up and from a run
    page four, and only a root-addressed path is right in both.
    """
    return f"experiments/{experiment_uid}/variants/{variant_uid}/index.html"


def _variant_link(experiment_uid: Any, variant_uid: Any) -> str:
    """A link to one variant's page, addressed from the root of the tree."""
    if variant_uid is None:
        return NOT_MEASURED
    return (
        f'<a href="{ROOT_TOKEN}{esc(variant_page_path(experiment_uid, variant_uid))}">'
        f"{esc(variant_uid)}</a>"
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
                ("input tokens", number(stats["input_tokens"])),
                ("generated tokens", number(stats["output_tokens"])),
                ("tokens", number(stats["total_tokens"])),
                ("tool calls", number(stats["tool_calls"])),
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
                ("input tokens", number(observations.get("input_tokens"))),
                ("generated tokens", number(observations.get("output_tokens"))),
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
                [
                    "variant",
                    _variant_link(run.get("experiment_uid"), run.get("variant_uid")),
                ],
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
    *TOKEN_HEADERS,
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
            # what one run cost: what was paid for, what the model produced, the
            # sum of them, and how often the agent reached for a tool
            number(observations.get("input_tokens")),
            number(observations.get("output_tokens")),
            number(observations.get("total_tokens")),
            number(observations.get("tool_call_count")),
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
                *_token_cells(row),
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
            *TOKEN_HEADERS,
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


def _experiment_description(experiment: dict[str, Any]) -> str:
    """What the experiment says about itself, in its own words.

    The description is recorded from the experiment file at plan time, so the
    report states the question the runs were meant to answer rather than a
    reader guessing it from a matrix. It is escaped and its line breaks are
    kept; a run record never reaches it, but an experiment file written in a
    hurry is still treated as text.
    """
    description = experiment.get("description")
    if not description:
        return ""
    paragraphs = [part.strip() for part in str(description).split("\n\n") if part.strip()]
    if not paragraphs:
        return ""
    body = "".join(f"<p>{esc(part)}</p>" for part in paragraphs)
    return f'<div class="prose experiment-description">{body}</div>'


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
        _experiment_description(experiment),
        cards(
            [
                ("runs", number(summary.get("runs"))),
                ("evaluated", number(summary.get("evaluated"))),
                ("success rate", percent(summary.get("success_rate"))),
                ("mean time", duration(summary.get("mean_duration_seconds"))),
                ("input tokens", number(summary.get("input_tokens"))),
                ("generated tokens", number(summary.get("output_tokens"))),
                ("tokens", number(summary.get("total_tokens"))),
                ("tool calls", number(summary.get("tool_calls"))),
            ]
        ),
        "<h2>Configuration ranking</h2>",
        _ranking(report.runs, {str(experiment.get("uid")): report.variants}),
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
                    _variant_link(experiment.get("uid"), variant.get("uid")),
                    _values(variant.get("values")),
                    f'<code>{esc(variant.get("config_hash"))}</code>',
                    "yes" if variant.get("is_baseline") else "no",
                    number(_variant_run_count(report.runs, variant.get("uid"))),
                ]
                for variant in report.variants
            ],
        )
        + '<p class="bar-note">a variant is one recording of one configuration; the '
        "ranking above counts the configurations, so several of these rows can share "
        "one ranking row &mdash; a uid opens that recording on its own page</p>",
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


def render_variant(report: VariantReport, *, generated_at: str | None = None) -> str:
    """One recording of one configuration: its own runs, and where it ranks.

    The ranking pooled the recordings of a configuration into a single row, so
    this page is what puts a single recording back on its own: what it planned,
    the runs it produced, the numbers of those runs alone, and the row of the
    ranking they were counted in — stated as the ranking states it, so the two
    cannot disagree.
    """
    variant = report.variant
    experiment = report.experiment
    summary = report.summary
    body = [
        "<h1>Variant</h1>",
        f'<p class="subtitle">{esc(variant.get("uid"))} of '
        f"{_experiment_link(experiment.get('uid'))}</p>",
        cards(
            [
                ("runs", number(summary.get("runs"))),
                ("evaluated", number(summary.get("evaluated"))),
                ("success rate", percent(summary.get("success_rate"))),
                ("mean time", duration(summary.get("mean_duration_seconds"))),
                ("input tokens", number(summary.get("input_tokens"))),
                ("generated tokens", number(summary.get("output_tokens"))),
                ("tokens", number(summary.get("total_tokens"))),
                ("tool calls", number(summary.get("tool_calls"))),
            ]
        ),
        "<h2>What this recording was</h2>",
        table(
            ["field", "value"],
            [
                ["variant", esc(variant.get("uid"))],
                ["experiment", _experiment_link(experiment.get("uid"))],
                ["configuration", _values(variant.get("values"))],
                ["config hash", f'<code>{esc(variant.get("config_hash"))}</code>'],
                ["baseline", "yes" if variant.get("is_baseline") else "no"],
            ],
        ),
    ]
    if report.configuration:
        body.append("<h2>In the configuration ranking</h2>")
        body.append(
            "<p class='muted'>the ranking states one row per configuration, over all "
            "of its recordings; these are the numbers of that row, not of this "
            "recording alone</p>"
        )
        body.append(
            table(
                [
                    "place",
                    "configuration",
                    "recordings #",
                    "runs #",
                    "evaluated #",
                    "success rate",
                    "mean time",
                    *MEAN_TOKEN_HEADERS,
                    "against the baseline",
                ],
                [
                    [
                        _place_cell(report.configuration),
                        _values(report.configuration.get("config")),
                        number(report.configuration.get("recordings") or 0),
                        number(report.configuration.get("runs") or 0),
                        number(report.configuration.get("evaluated") or 0),
                        percent(report.configuration.get("success_rate")),
                        duration(report.configuration.get("mean_duration_seconds")),
                        *_mean_token_cells(report.configuration),
                        esc(report.configuration.get("vs_baseline") or ""),
                    ]
                ],
            )
        )
    if report.siblings:
        body.append("<h2>The other recordings of this configuration</h2>")
        body.append(
            "<p class='muted'>the same values, recorded under another variant uid; "
            "the ranking counts this page's runs and these together</p>"
        )
        body.append(
            table(
                [
                    "variant",
                    "baseline",
                    "runs #",
                    "evaluated #",
                    "passed #",
                    "success rate",
                    "mean time",
                    *TOKEN_HEADERS,
                ],
                [
                    [
                        _variant_link(experiment.get("uid"), row.get("uid")),
                        "yes" if row.get("is_baseline") else "no",
                        number(row.get("runs") or 0),
                        number(row.get("evaluated") or 0),
                        number(row.get("passed") or 0),
                        percent(row.get("success_rate")),
                        duration(row.get("mean_duration_seconds")),
                        *_token_cells(row),
                    ]
                    for row in report.siblings
                ],
            )
        )
    body.append("<h2>Runs of this recording</h2>")
    body.append(
        "<p class='muted'>in the order they started; the parameters column is the "
        "configuration each run was executed under</p>"
    )
    body.append(_runs_table(report.runs, [variant]))
    body.append("<h2>Not verified</h2>")
    body.append(_notice(report.unverified))
    return page(
        f"Variant {variant.get('uid')}", "".join(body), generated_at=generated_at
    )


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
                ("input tokens", number(summary.get("input_tokens"))),
                ("generated tokens", number(summary.get("output_tokens"))),
                ("tokens", number(summary.get("total_tokens"))),
                ("tool calls", number(summary.get("tool_calls"))),
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
                ("input tokens", number(summary.get("input_tokens"))),
                ("generated tokens", number(summary.get("output_tokens"))),
                ("tokens", number(summary.get("total_tokens"))),
                ("tool calls", number(summary.get("tool_calls"))),
            ]
        ),
    ]
    if report.experiments:
        body.append("<h2>Experiments this subject took part in</h2>")
        body.append(
            table(
                ["experiment", "title", "type", "runs #", "evaluated #", "passed #",
                 "success rate", "mean time", *TOKEN_HEADERS],
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
                        *_token_cells(row),
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
                 "mean time", *TOKEN_HEADERS],
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
                        *_token_cells(row),
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


def _docs_menu(documents: list[Document], current: str | None) -> str:
    """The menu that travels with every documentation page.

    Documents are listed under the part of the checkout they came from, with
    the headings of the one being read listed under it, so a reader knows both
    where they are and what is left to read.
    """
    paths = page_paths(documents)
    groups: dict[str, list[Document]] = {}
    for document in documents:
        groups.setdefault(group_of(document.relpath), []).append(document)
    parts: list[str] = []
    for name in sorted(groups, key=group_order):
        items: list[str] = []
        for document in groups[name]:
            href = f"{ROOT_TOKEN}{esc(paths[document.relpath])}"
            css = ' class="current"' if document.relpath == current else ""
            entry = f'<li><a{css} href="{href}">{esc(document.title)}</a>'
            if document.relpath == current and document.headings:
                entry += '<span class="toc">' + "".join(
                    f'<a href="#{esc(anchor)}">{esc(title)}</a>'
                    for level, anchor, title in document.headings
                    if level <= 3
                ) + "</span>"
            items.append(entry + "</li>")
        parts.append(
            f'<div class="menu-group"><p class="menu-title">{esc(name)}</p>'
            f'<ul>{"".join(items)}</ul></div>'
        )
    return f'<nav class="docs-menu">{"".join(parts)}</nav>'


def render_docs_index(documents: list[Document], *, generated_at: str | None = None) -> str:
    """The landing page of the documentation: the menu, and what is in it.

    The page is written even when the checkout held no document to read, and
    it then says so: an empty directory is a fact about the report, not a bug
    it should hide.
    """
    if not documents:
        body = (
            "<h1>Documentation</h1>"
            '<p class="subtitle">the documents the project wrote about itself</p>'
            '<p class="muted">no document was found next to this report. The tree is '
            "written from the checkout the report was generated in, so a report "
            "written elsewhere carries the history and not the prose.</p>"
        )
        return page("Documentation", body, generated_at=generated_at)
    paths = page_paths(documents)
    listing = table(
        ["document", "section", "path"],
        [
            [
                f'<a href="{ROOT_TOKEN}{esc(paths[document.relpath])}">'
                f"{esc(document.title)}</a>",
                esc(group_of(document.relpath)),
                f'<code>{esc(document.relpath)}</code>',
            ]
            for document in documents
        ],
    )
    body = (
        "<h1>Documentation</h1>"
        '<p class="subtitle">the documents the project wrote about itself, rendered '
        "from the checkout this report was generated in</p>"
        f'<div class="docs-layout">{_docs_menu(documents, None)}'
        f'<div class="prose">{listing}</div></div>'
    )
    return page("Documentation", body, generated_at=generated_at)


def render_docs_page(
    document: Document, documents: list[Document], *, generated_at: str | None = None
) -> str:
    """One document, rendered, with the menu beside it."""
    body = (
        f'<div class="docs-layout">{_docs_menu(documents, document.relpath)}'
        f'<article class="prose">{document.body}</article></div>'
    )
    return page(document.title, body, generated_at=generated_at)


def asset_names() -> tuple[str, ...]:
    return ASSET_NAMES


def write_report_tree(
    root: Path | str,
    data: HistoryData,
    *,
    generated_at: str | None = None,
    dataset: Any = None,
    docs_root: Path | str | None = None,
) -> list[Path]:
    """Write the report tree under ``root``; returns every file written.

    ``dataset`` is the dataset the tasks came from. It is optional: a report of
    a database on its own loses the task prose, says so on each task page, and
    stays correct about everything else.

    ``docs_root`` is the checkout whose documents are published under ``docs/``.
    It is optional for the same reason: a report generated away from the
    checkout carries the history and says the prose was not found, rather than
    inventing it or leaving a menu of links to pages that were never written.
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
        for planned in data.variants_for(uid):
            variant_report = build_variant_report(data, uid, str(planned.get("uid")))
            if variant_report is not None:
                write(
                    variant_page_path(uid, planned.get("uid")),
                    render_variant(variant_report, generated_at=generated_at),
                )
    for task in data.tasks:
        uid = str(task["uid"])
        write(
            f"tasks/{uid}/index.html",
            render_task(
                build_task_report(data, uid, dataset=dataset), generated_at=generated_at
            ),
        )

    documents = discover_documents(Path(docs_root)) if docs_root else []
    write("docs/index.html", render_docs_index(documents, generated_at=generated_at))
    for document in documents:
        write(
            page_paths(documents)[document.relpath],
            render_docs_page(document, documents, generated_at=generated_at),
        )

    stats = dashboard(data)
    write("tasks/index.html", _task_listing(data))
    write(
        "agents/index.html",
        _group_listing(
            "Agents",
            "one row per agent identity; a row opens that agent's experiments and runs",
            stats["agents"],
            "agent",
            "agents",
        ),
    )
    write(
        "runtimes/index.html",
        _group_listing(
            "Runtimes",
            "one row per runtime; a row opens that runtime's experiments and runs",
            stats["runtimes"],
            "runtime",
            "runtimes",
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


def _group_listing(
    title: str, subtitle: str, rows: list[dict[str, Any]], label: str, directory: str
) -> str:
    """A listing whose first column opens the subject's own page.

    The directory is passed in because the listing and the page it links to sit
    next to each other in the tree (``agents/index.html`` links to
    ``agents/<slug>/index.html``), and a link that guesses the directory is a
    link to a page that may not exist.
    """
    return render_listing(
        title,
        subtitle,
        [
            [
                f'<a href="{esc(slugify(str(row.get(label))))}/index.html">'
                f"{esc(row.get(label))}</a>",
                number(row.get("runs") or 0),
                number(row.get("evaluated") or 0),
                number(row.get("passed") or 0),
                percent(row.get("success_rate")),
                duration(row.get("mean_duration_seconds")),
                *_token_cells(row),
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
            *TOKEN_HEADERS,
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
