"""ADR-0003, read from the end that the shipped build got wrong.

Only the newest segment — the one the journal appends to — may end in an
incomplete frame. Read with the wrong eyes, a damaged sealed segment is a torn
tail: the restart truncates it, replays what is left, and reports a healthy
store that is one transaction short. The capture under
`docs/incidents/captures/INC-0004/` is that store, and `INC-0004` is the ticket.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TORN_TAIL = b"\x00\x00\x01\x00"


def interrupted_store(root: Path, *, rounds: int = 1) -> list[Path]:
    """A store interrupted inside ``compact()``, once per round.

    Compaction rotates first and prunes last, so a crash in that window leaves a
    sealed segment and the fresh append target coexisting — the state the capture
    came from. Each round writes five transactions: two puts, a lease, an
    acknowledgement, and one more put. Round N therefore ends at sequence 5 * N.
    """
    from walqueue import InjectedCrash, Queue

    def hook(point: str) -> None:
        if point == "compact.rotated":
            raise InjectedCrash(point)

    for index in range(1, rounds + 1):
        queue = Queue(root, hook=hook)
        queue.put(f"inv-{index}-1", {"cents": 100, "tenant": "north"})
        queue.put(f"inv-{index}-2", {"cents": 200, "tenant": "north"})
        for lease in queue.reserve(f"w{index}", now=100, lease_seconds=600):
            queue.ack(lease, now=110)
        queue.put(f"inv-{index}-3", {"cents": 300, "tenant": "south"})
        try:
            queue.compact()
        except InjectedCrash:
            pass
    return sorted(root.glob("wal-*.log"))


def capture() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        found = candidate / "docs" / "incidents" / "captures" / "INC-0004"
        if found.is_dir():
            return found / "corrupted_segment.wal"
    raise RuntimeError("hidden tests run inside a prepared walqueue workspace")


def test_a_sealed_segment_that_ends_mid_frame_refuses_to_open(tmp_path):
    from walqueue import CorruptStore, Queue

    store = tmp_path / "store"
    sealed, _newest = interrupted_store(store)
    sealed.write_bytes(sealed.read_bytes()[:-11])
    with pytest.raises(CorruptStore):
        Queue(store)


def test_refusing_a_store_writes_nothing_to_it(tmp_path):
    from walqueue import CorruptStore, Queue

    store = tmp_path / "store"
    sealed, _newest = interrupted_store(store)
    sealed.write_bytes(sealed.read_bytes()[:-11])
    damaged = sealed.read_bytes()
    with pytest.raises(CorruptStore):
        Queue(store)
    assert sealed.read_bytes() == damaged, (
        "a store that cannot be opened must not have been modified; truncating a "
        "sealed segment is not a repair, it is the loss the ticket is about"
    )


def test_a_damaged_sealed_segment_never_opens_as_a_healthy_shorter_store(tmp_path):
    """The exact symptom: the client was shown 5, the store reports 4."""
    from walqueue import CorruptStore, Queue

    store = tmp_path / "store"
    sealed, _newest = interrupted_store(store)
    sealed.write_bytes(sealed.read_bytes()[:-11])
    try:
        opened = Queue(store)
    except CorruptStore:
        return
    raise AssertionError(
        f"the store opened at sequence {opened.export()['sequence']} and "
        f"{opened.stats()}; the client had been shown 5, and the transaction it is "
        "missing is the one the truncation ate"
    )


def test_the_allowance_lands_on_exactly_one_segment(tmp_path):
    from walqueue import CorruptStore, Queue

    store = tmp_path / "store"
    sealed, newest = interrupted_store(store)
    sealed.write_bytes(sealed.read_bytes()[:-11])
    newest.write_bytes(newest.read_bytes() + TORN_TAIL)
    with pytest.raises(CorruptStore):
        Queue(store)


def test_the_allowance_follows_the_name_not_the_list(tmp_path):
    """Three segments: the newest of them may be torn, the two before it may not."""
    from walqueue import CorruptStore, Queue

    for which, expect_raise in (("newest", False), ("middle", True), ("oldest", True)):
        store = tmp_path / f"store-{which}"
        first, middle, newest = interrupted_store(store, rounds=2)
        target = {"oldest": first, "middle": middle, "newest": newest}[which]
        if which == "newest":
            target.write_bytes(target.read_bytes() + TORN_TAIL)
        else:
            target.write_bytes(target.read_bytes()[:-11])
        damaged = (first.read_bytes(), middle.read_bytes(), newest.read_bytes())
        if not expect_raise:
            assert Queue(store).export()["sequence"] == 10
            continue
        with pytest.raises(CorruptStore):
            Queue(store)
        assert (first.read_bytes(), middle.read_bytes(), newest.read_bytes()) == damaged, (
            f"the {which} segment was rewritten while the store was being refused"
        )


def test_the_capture_shipped_with_the_repository_is_a_damaged_sealed_segment():
    from walqueue import CorruptStore
    from walqueue.codec import decode

    data = capture().read_bytes()
    assert decode(data, allow_torn_tail=True).torn is True
    with pytest.raises(CorruptStore):
        decode(data, allow_torn_tail=False)
