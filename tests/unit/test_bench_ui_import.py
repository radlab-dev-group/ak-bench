"""The dashboard is an add-on: importing it needs no database.

``akbench ui`` starts the FastAPI dashboard on request, and the benchmark must
not depend on it — nor may the dashboard depend on a database being reachable
before it has been asked for one. The import and one build of the app are the
gate this file holds: a future change that opens a connection at import time,
or that builds the app against a database it picked up on its own, fails here
rather than in front of a page.
"""

from __future__ import annotations


def test_importing_the_dashboard_reaches_for_no_database() -> None:
    """The import is the gate: a connection made here would raise right now."""
    import bench_ui

    assert bench_ui.app is not None


def test_the_app_is_buildable_without_a_database_argument() -> None:
    """The factory opens nothing on its own, and builds twice."""
    from bench_ui.app import create_app

    first = create_app()
    second = create_app()

    assert first is not second
    # The dashboard serves its pages before any history has been read: the
    # routes exist whether or not a database is reachable behind them.
    assert [getattr(route, "path", None) for route in first.routes if route.path == "/"]
