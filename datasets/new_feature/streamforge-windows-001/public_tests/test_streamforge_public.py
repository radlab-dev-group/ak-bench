from streamforge import Event, Pipeline, Processor, Window


def test_fixed_window_and_source_retry():
    processor = Processor(Pipeline(("input",), (Window("minute", "fixed", size=60),)))
    event = Event("input", 0, "sale", "shop", 12, 7)
    assert processor.ingest(event) == []
    assert processor.ingest(event) == []
    (change,) = processor.advance("input", 60)
    assert (change.sequence, change.operation) == (1, "upsert")
    assert (change.result.start, change.result.end, change.result.total) == (0, 60, 7)


def test_checkpoint_resumes_offsets_and_output(tmp_path):
    pipeline = Pipeline(("a",), (Window("fixed", "fixed", size=10),), lateness=20)
    processor = Processor(pipeline)
    processor.ingest(Event("a", 0, "one", "key", 1, 5))
    processor.advance("a", 10)
    path = tmp_path / "state.json"
    processor.checkpoint(path)
    restored = Processor.restore(pipeline, path)
    changes = restored.ingest(Event("a", 1, "two", "key", 2, 3))
    assert [change.operation for change in changes] == ["retract", "upsert"]
    assert [change.sequence for change in changes] == [2, 3]
    assert changes[-1].result.total == 8
