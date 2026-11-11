"""The failing scenario, proven from every side.

These tests fail on the base commit (the defect is in the base code) and
pass once the retry is repaired.
"""

from __future__ import annotations

import pytest

from pipeline import Pipeline


def flaky(calls, name, fn):
    def stage(value):
        calls[name] += 1
        if calls[name] == 1:
            raise RuntimeError(f"{name} failed once")
        return fn(value)
    return stage


def test_a_retry_resumes_at_the_failed_stage():
    calls = {"first": 0, "second": 0, "third": 0}
    pipeline = Pipeline()
    pipeline.add_stage("first", lambda v: calls.__setitem__("first", calls["first"] + 1) or v + 1)
    pipeline.add_stage("second", flaky(calls, "second", lambda v: v * 10))
    pipeline.add_stage("third", lambda v: calls.__setitem__("third", calls["third"] + 1) or v + 100)
    # first stage succeeds at once; second fails once, then succeeds.
    assert pipeline.run(1) == 120
    assert calls == {"first": 1, "second": 2, "third": 1}


def test_a_failure_in_the_first_stage_retries_from_there():
    calls = {"first": 0, "second": 0}
    pipeline = Pipeline()
    pipeline.add_stage("first", flaky(calls, "first", lambda v: v + 1))
    pipeline.add_stage("second", lambda v: calls.__setitem__("second", calls["second"] + 1) or v * 2)
    assert pipeline.run(3) == 8
    assert calls == {"first": 2, "second": 1}


def test_a_failure_in_the_last_stage_does_not_rerun_earlier_stages():
    calls = {"first": 0, "last": 0}
    pipeline = Pipeline()
    pipeline.add_stage("first", lambda v: calls.__setitem__("first", calls["first"] + 1) or v + 1)
    pipeline.add_stage("last", flaky(calls, "last", lambda v: v * 3))
    assert pipeline.run(2) == 9
    assert calls == {"first": 1, "last": 2}


def test_a_stage_that_fails_twice_still_raises():
    def always(value):
        raise RuntimeError("always")
    pipeline = Pipeline()
    pipeline.add_stage("first", lambda v: v + 1)
    pipeline.add_stage("bad", always)
    with pytest.raises(RuntimeError):
        pipeline.run(1)


def test_the_happy_path_still_works():
    pipeline = Pipeline()
    pipeline.add_stage("inc", lambda v: v + 1)
    pipeline.add_stage("double", lambda v: v * 2)
    assert pipeline.run(3) == 8
