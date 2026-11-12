"""Two checks you can run while you work: the capture, and the rule it breaks.

The first two pass on the build you were given and must keep passing. The last
one is the ticket: it fails there, because that build opens the store instead of
refusing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _source_root() -> Path:
    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "src" / "walqueue").is_dir():
            return candidate
    raise RuntimeError("this test runs inside a prepared walqueue workspace")


ROOT = _source_root()
sys.path.insert(0, str(ROOT / "src"))

from walqueue import CorruptStore, InjectedCrash, Queue  # noqa: E402
from walqueue.codec import decode  # noqa: E402

CAPTURE = ROOT / "docs" / "incidents" / "captures" / "INC-0004" / "corrupted_segment.wal"


def crashed_store(root: Path, *, tear: str) -> tuple[Path, Path]:
    """The capture, rebuilt: a store interrupted inside compact().

    Two segments coexist when the crash lands in that window, and the older one
    has already stopped taking appends. ``tear`` decides which of them loses the
    end of its last frame.
    """

    def hook(point: str) -> None:
        if point == "compact.rotated":
            raise InjectedCrash(point)

    queue = Queue(root, hook=hook)
    queue.put("inv-1", {"cents": 100})
    queue.put("inv-2", {"cents": 200})
    for lease in queue.reserve("w1", now=100, lease_seconds=600):
        queue.ack(lease, now=110)
    queue.put("inv-3", {"cents": 300})
    try:
        queue.compact()
    except InjectedCrash:
        pass
    sealed, newest = sorted(root.glob("wal-*.log"))
    if tear in ("sealed", "both"):
        sealed.write_bytes(sealed.read_bytes()[:-11])
    if tear in ("newest", "both"):
        newest.write_bytes(newest.read_bytes() + b"\x00\x00\x01\x00")
    return sealed, newest


def test_the_capture_is_a_frame_that_stops_short_of_its_digest():
    data = CAPTURE.read_bytes()
    assert decode(data, allow_torn_tail=True).torn is True
    with pytest.raises(CorruptStore):
        decode(data, allow_torn_tail=False)


def test_a_torn_tail_in_the_newest_segment_is_repaired_and_remembered(tmp_path):
    store = tmp_path / "store"
    sealed, newest = crashed_store(store, tear="newest")
    sealed_before = sealed.read_bytes()

    assert Queue(store).export()["sequence"] == 5
    assert newest.read_bytes() == b"", "the torn tail was not truncated"
    assert sealed.read_bytes() == sealed_before, "a sealed segment was rewritten"
    assert Queue(store).export()["sequence"] == 5, "the repair was not persisted"


def test_a_sealed_segment_may_not_end_in_a_torn_frame(tmp_path):
    store = tmp_path / "store"
    sealed, _ = crashed_store(store, tear="sealed")
    damaged = sealed.read_bytes()
    with pytest.raises(CorruptStore):
        Queue(store)
    assert sealed.read_bytes() == damaged, "refusing a store must not modify it"
