"""The symptom a developer can reproduce: early stages run twice on retry."""

from __future__ import annotations

from pipeline import Pipeline


def test_a_retry_resumes_at_the_failed_stage():
    calls = {"first": 0, "second": 0}

    def first(value):
        calls["first"] += 1
        return value + 1

    def second(value):
        calls["second"] += 1
        if calls["second"] == 1:
            raise RuntimeError("boom")
        return value * 10

    pipeline = Pipeline()
    pipeline.add_stage("first", first)
    pipeline.add_stage("second", second)
    assert pipeline.run(1) == 20
    assert calls == {"first": 1, "second": 2}
