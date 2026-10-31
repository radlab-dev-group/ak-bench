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
from pathlib import Path, PurePosixPath
from typing import Any

from akbench.reporting.data import (
    ExperimentReport,
    HistoryData,
    TaskReport,
    build_experiment_report,
    build_task_report,
    dashboard,
    duration_seconds,
    unverified_configurations,
    variant_comparison,
    verdict_of,
)

STYLE_NAME = "assets/style.css"
ASSET_NAMES: tuple[str, ...] = (STYLE_NAME,)
NOT_MEASURED = "not measured"
CSS_TOKEN = "{{css}}"
ROOT_TOKEN = "{{root}}"

STYLE = """
/* AK-Bench report — a phosphor terminal look, deliberately CSS only, no script.
   The palette is CRT, the content is not: every value stays as it was measured.
   A light scheme is used for print, because a black page wastes a toner. */
:root {
  --bg: #06090a; --panel: #0b1214; --fg: #b8f5c8; --bright: #eafff0;
  --muted: #5f8a72; --line: #1d3a2c; --head: #10201a;
  --pass: #46f08a; --fail: #ff6b5e; --warn: #ffc857; --accent: #35e0c0;
  --glow: 0 0 6px rgba(70, 240, 138, .25);
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0; padding: 2rem 1.5rem 4rem; background: var(--bg); color: var(--fg);
  font: 14px/1.55 ui-monospace, "SFMono-Regular", "JetBrains Mono", Menlo, Consolas, monospace;
  text-shadow: var(--glow);
}
/* scanlines and the vignette of a tube, both behind the content */
body::before {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 2;
  background: repeating-linear-gradient(
    to bottom, rgba(0, 0, 0, 0) 0 2px, rgba(0, 0, 0, .22) 2px 4px);
}
body::after {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 3;
  background: radial-gradient(ellipse at center, rgba(0, 0, 0, 0) 55%, rgba(0, 0, 0, .55) 100%);
}
main {
  position: relative; z-index: 1; max-width: 72rem; margin: 0 auto;
  border: 1px solid var(--line); background: var(--panel); padding: 1.5rem 1.6rem 2rem;
  box-shadow: inset 0 0 40px rgba(0, 0, 0, .6);
}
h1 {
  font-size: 1.15rem; margin: 0 0 .35rem; letter-spacing: .18em; text-transform: uppercase;
  color: var(--bright);
}
h1::before { content: "> "; color: var(--accent); }
h2 {
  font-size: .85rem; margin: 2.2rem 0 .6rem; letter-spacing: .16em; text-transform: uppercase;
  color: var(--accent); border-bottom: 1px dashed var(--line); padding-bottom: .3rem;
}
h2::before { content: "── "; color: var(--line); }
h3 {
  font-size: .74rem; margin: 1.2rem 0 .35rem; letter-spacing: .14em; text-transform: uppercase;
  color: var(--muted);
}
a { color: var(--accent); text-decoration: none; border-bottom: 1px dotted var(--line); }
a:hover { color: var(--bright); background: rgba(53, 224, 192, .12); text-decoration: none; }
.nav { font-size: .8rem; color: var(--muted); margin-bottom: 1.4rem; letter-spacing: .08em; }
.nav::before { content: "PATH "; color: var(--muted); }
.subtitle { color: var(--muted); margin: 0 0 1.4rem; font-size: .85rem; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1.2rem; font-size: .85rem; }
th, td {
  border-bottom: 1px solid var(--line); padding: .45rem .6rem;
  text-align: left; vertical-align: top; font-variant-numeric: tabular-nums;
}
th {
  background: var(--head); color: var(--accent); font-weight: 600;
  font-size: .72rem; letter-spacing: .12em; text-transform: uppercase;
  border-bottom: 1px solid var(--accent);
}
tbody tr:hover { background: rgba(53, 224, 192, .06); }
td.num, th.num { text-align: right; }
.cards { display: flex; flex-wrap: wrap; gap: .7rem; margin: 1.1rem 0 1.7rem; }
.card {
  border: 1px solid var(--line); padding: .65rem .85rem; min-width: 9.5rem;
  background: rgba(53, 224, 192, .04); box-shadow: inset 0 0 18px rgba(0, 0, 0, .45);
}
.card .label {
  color: var(--muted); font-size: .68rem; letter-spacing: .14em; text-transform: uppercase;
}
.card .value { font-size: 1.3rem; color: var(--bright); }
.pass { color: var(--pass); }
.fail { color: var(--fail); text-shadow: 0 0 6px rgba(255, 107, 94, .3); }
.warn { color: var(--warn); }
.muted { color: var(--muted); }
.badge {
  border: 1px solid var(--line); padding: 0 .45rem; font-size: .72rem;
  letter-spacing: .1em; text-transform: uppercase; color: var(--muted); white-space: nowrap;
}
.badge.warn { border-color: var(--warn); color: var(--warn); }
.badge.pass { border-color: var(--pass); color: var(--pass); }
.notice {
  border-left: 3px solid var(--warn); background: rgba(255, 200, 87, .07);
  padding: .7rem .9rem; margin: .9rem 0; font-size: .85rem;
}
code {
  font: .8rem/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-all; color: var(--bright); background: rgba(0, 0, 0, .35); padding: 0 .2rem;
}
footer {
  margin-top: 2.5rem; color: var(--muted); font-size: .75rem;
  letter-spacing: .1em; border-top: 1px dashed var(--line); padding-top: .7rem;
}
footer::before { content: "└─ "; color: var(--line); }
/* the ranking and its bars: a measurement drawn to scale, never decoration */
.place { font-size: 1.15rem; color: var(--muted); }
.place.top { color: var(--pass); }
.place.row1 { color: var(--bright); }
.bars { display: grid; gap: .4rem; margin: .4rem 0 1.2rem; }
.bar-row {
  display: grid; grid-template-columns: minmax(9rem, 22rem) 1fr; gap: .7rem;
  align-items: center; font-size: .8rem;
}
.bar-row .who { color: var(--fg); overflow-wrap: anywhere; }
.bar {
  position: relative; height: .8rem; background: rgba(0, 0, 0, .45);
  border: 1px solid var(--line); min-width: 6rem;
}
.bar > span {
  position: absolute; left: 0; top: 0; bottom: 0; background: var(--accent);
  box-shadow: 0 0 8px rgba(53, 224, 192, .35);
}
.bar.cost > span { background: var(--warn); box-shadow: 0 0 8px rgba(255, 200, 87, .28); }
.bar-note { color: var(--muted); font-size: .75rem; margin: -.6rem 0 1.2rem; }
@media print {
  .bar { border-color: #999; background: #f2f2f2; }
  .bar > span { background: #00664f; box-shadow: none; }
  .bar.cost > span { background: #8a6100; box-shadow: none; }
  :root { --bg: #fff; --panel: #fff; --fg: #111; --bright: #000; --muted: #555;
          --line: #bbb; --head: #eee; --accent: #00664f; --pass: #0a7d38; --warn: #8a6100;
          --fail: #b3261e; --glow: none; }
  body { font-size: 11px; }
  body::before, body::after { display: none; }
  main { border: none; box-shadow: none; padding: 0; }
}
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
        f'<th class="num">{esc(header[:-2].strip())}</th>'
        if is_num(header)
        else f"<th>{esc(header)}</th>"
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
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


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
            f'<a href="{ROOT_TOKEN}tasks/index.html">tasks</a></p>'
        )
    head = (
        f"<style>{STYLE}</style>" if standalone else f'<link rel="stylesheet" href="{CSS_TOKEN}">'
    )
    stamp = f"<footer>generated {esc(generated_at)} from the recorded history</footer>"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{esc(title)}</title>"
        f"{head}</head>"
        f"<body><main>{nav}{body}{stamp}</main></body></html>\n"
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


def _notice(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return '<p class="pass">every recorded configuration states it was verified.</p>'
    rows = [
        [
            esc(item.get("kind")),
            esc(item.get("subject")),
            f'<span class="badge warn">{esc(item.get("status"))}</span>',
            esc(item.get("run_uid") or ""),
            esc(item.get("note") or ""),
        ]
        for item in findings
    ]
    return (
        '<div class="notice"><strong>Configurations that are not verified.</strong> '
        "They stay in the report, because a result produced under them is only as "
        "trustworthy as they are.</div>" + table(["kind", "subject", "status", "run", "note"], rows)
    )


def _comparison_table(rows: list[dict[str, Any]], label: str) -> str:
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
    """The leading configuration of every experiment that had more than one."""
    rows: list[list[str]] = []
    for experiment in data.experiments:
        uid = str(experiment.get("uid"))
        ranked = variant_comparison(data.runs_for_experiment(uid), data.variants_for(uid))
        leaders = [row for row in ranked if row.get("place") == 1]
        if not leaders:
            continue
        for row in leaders:
            label = esc(row.get("config"))
            if row.get("is_baseline"):
                label += ' <span class="badge">baseline</span>'
            rows.append(
                [
                    _experiment_link(uid),
                    label,
                    number(row.get("runs") or 0),
                    percent(row.get("success_rate")),
                    duration(row.get("mean_duration_seconds")),
                    number(row.get("total_tokens")),
                ]
            )
    if not rows:
        return (
            '<p class="muted">no experiment has ranked more than one evaluated '
            "configuration yet</p>"
        )
    return table(
        ["experiment", "leading configuration", "runs #", "success rate", "mean time", "tokens #"],
        rows,
    )


def _experiment_link(uid: Any) -> str:
    """A link to an experiment report, relative to the page that lists it."""
    return f'<a href="experiments/{esc(uid)}/index.html">{esc(uid)}</a>'


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
        "<h2>Verdicts</h2>",
        table(
            ["verdict", "runs #", "share of evaluated"],
            [
                [
                    esc(verdict),
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
        "<h2>Leading configurations</h2>",
        _leaderboard(data),
        "<h2>Results by category</h2>",
        _comparison_table(stats["by_category"], "category"),
        "<h2>Results by difficulty</h2>",
        _comparison_table(stats["by_difficulty"], "difficulty"),
        "<h2>Agent comparison</h2>",
        _comparison_table(stats["agents"], "agent"),
        "<h2>Runtime and router comparison</h2>",
        _comparison_table(stats["runtimes"], "runtime"),
        "<h2>Plugin comparison</h2>",
        table(
            ["plugin", "runs #", "enabled runs #", "versions", "verification"],
            [
                [
                    esc(row.get("plugin")),
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
                    esc(row.get("requested")),
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


def _runs_table(runs: list[dict[str, Any]]) -> str:
    rows = []
    for run in runs:
        evaluation = run.get("evaluation") if isinstance(run.get("evaluation"), dict) else {}
        observations = (
            run.get("observations") if isinstance(run.get("observations"), dict) else {}
        )
        rows.append(
            [
                esc(run.get("uid")),
                esc(run.get("task_uid")),
                esc(run.get("agent")),
                esc(run.get("variant_uid")),
                esc(run.get("status")),
                esc(verdict_of(run)),
                number(evaluation.get("score"), digits=3),
                duration(duration_seconds(run)),
                number(observations.get("total_tokens")),
                esc(run.get("failure_class")),
                esc(run.get("error_message") or ""),
            ]
        )
    return table(
        [
            "run",
            "task",
            "agent",
            "variant",
            "status",
            "verdict",
            "score #",
            "time",
            "tokens #",
            "failure class",
            "error",
        ],
        rows,
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
        _runs_table(_not_passed(report.runs)),
        "<h2>All runs</h2>",
        _runs_table(report.runs),
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
        "<h2>Definition</h2>",
        table(
            ["field", "value"],
            [
                ["category", esc(task.get("category"))],
                ["difficulty", esc(task.get("difficulty"))],
                ["evaluator", esc(task.get("evaluator"))],
                ["base commit", esc(task.get("base_commit"))],
                ["repository", esc(task.get("repository_uid"))],
                ["snapshot digest", f'<code>{esc(task.get("snapshot_digest"))}</code>'],
            ],
        ),
        "<h2>Runs of this task</h2>",
        _runs_table(report.runs),
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


def render_listing(
    title: str, subtitle: str, rows: list[list[str]], headers: list[str]
) -> str:
    body = f"<h1>{esc(title)}</h1><p class='subtitle'>{esc(subtitle)}</p>" + table(headers, rows)
    return page(title, body)


def asset_names() -> tuple[str, ...]:
    return ASSET_NAMES


def write_report_tree(
    root: Path | str, data: HistoryData, *, generated_at: str | None = None
) -> list[Path]:
    """Write the report tree under ``root``; returns every file written."""
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
            render_task(build_task_report(data, uid), generated_at=generated_at),
        )

    stats = dashboard(data)
    write("tasks/index.html", _task_listing(data))
    write(
        "agents/index.html",
        _group_listing("Agents", "one row per agent identity", stats["agents"], "agent"),
    )
    write(
        "runtimes/index.html",
        _group_listing("Runtimes", "one row per runtime", stats["runtimes"], "runtime"),
    )
    write("plugins/index.html", _plugin_listing(stats["plugins"]))
    write("models/index.html", _model_listing(stats["models"]))
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
                esc(row.get("plugin")),
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
                esc(row.get("requested")),
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
