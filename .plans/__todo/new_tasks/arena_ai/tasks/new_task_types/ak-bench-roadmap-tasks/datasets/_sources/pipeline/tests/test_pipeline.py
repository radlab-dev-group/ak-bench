"""The finished part of the fixture: the happy path.

The suite deliberately never fails a stage, so a defect in the retry
behaviour is invisible here.
"""

from __future__ import annotations

from pipeline import Pipeline


def test_stages_run_in_the_order_they_were_added():
    pipeline = Pipeline()
    pipeline.add_stage("inc", lambda value: value + 1)
    pipeline.add_stage("double", lambda value: value * 2)
    assert pipeline.run(3) == 8


def test_an_empty_pipeline_returns_the_value():
    assert Pipeline().run(42) == 42


def test_stage_names_do_not_change_the_order():
    pipeline = Pipeline()
    pipeline.add_stage("z-first", lambda value: value + "a")
    pipeline.add_stage("a-second", lambda value: value + "b")
    assert pipeline.run("") == "ab"
