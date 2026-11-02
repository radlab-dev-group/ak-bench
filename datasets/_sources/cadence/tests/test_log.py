"""The log survives a crash in the middle of a write."""

from cadence.log import WriteAheadLog


def test_records_come_back_in_the_order_they_were_written(tmp_path):
    log = WriteAheadLog(tmp_path / "job.log")
    log.append("scheduled", {"subject": "a"}, at=1.0)
    log.append("started", {"subject": "a"}, at=2.0)
    kinds = [(record.lsn, record.kind) for record in log.records()]
    assert kinds == [(1, "scheduled"), (2, "started")]


def test_a_torn_tail_is_dropped_rather_than_raised(tmp_path):
    log = WriteAheadLog(tmp_path / "job.log")
    log.append("scheduled", {"subject": "a"}, at=1.0)
    with (tmp_path / "job.log").open("a", encoding="utf-8") as handle:
        handle.write('{"lsn": 2, "kind": "started", "at": 2.0, "payloa')
    assert [record.lsn for record in log.records()] == [1]
    assert log.next_lsn() == 2


def test_an_idempotency_key_is_written_once(tmp_path):
    log = WriteAheadLog(tmp_path / "job.log")
    log.append("started", {"subject": "a"}, at=1.0, idempotency_key="a:started:1")
    log.append("started", {"subject": "a"}, at=9.0, idempotency_key="a:started:1")
    assert log.size() == 1
