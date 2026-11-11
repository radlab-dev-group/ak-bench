"""Harness: the test file must pass on the correct code and fail on the
defective code. The defective variant is a one-line mutation of the
fixture, swapped in for a second run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import playlist

TEST_REL = Path('tests/test_queue_agent.py')
DEFECTIVE = {'src/playlist/queue.py': '"""Playing an album in order.\n\nThe rules:\n\n1. Album order is by disc first, then by track number within the disc,\n   then by track id. Disc 1 plays in full before disc 2 starts, whatever\n   the track numbers say.\n2. A queue is the album order with skipped tracks removed. Skipping never\n   reorders what remains.\n3. The total duration is the sum of the track durations, in seconds.\n"""\n\nfrom __future__ import annotations\n\nfrom collections.abc import Collection, Iterable\n\nfrom playlist.model import Track\n\n\ndef album_order(tracks: Iterable[Track]) -> list[Track]:\n    """The tracks in album order, under the rules above."""\n    return sorted(tracks, key=lambda track: (track.track_no, track.disc, track.track_id))\n\n\ndef build_queue(\n    tracks: Iterable[Track], *, skip_ids: Collection[str] = ()\n) -> list[Track]:\n    """The album order without the skipped tracks."""\n    skip = set(skip_ids)\n    return [track for track in album_order(tracks) if track.track_id not in skip]\n\n\ndef total_duration(tracks: Iterable[Track]) -> int:\n    """The sum of the track durations, in seconds."""\n    return sum(track.duration for track in tracks)\n'}

SAMPLE = '"""Tests for playlist.queue: album order, skipping, duration."""\n\nfrom __future__ import annotations\n\nfrom playlist.model import Track\nfrom playlist.queue import album_order, build_queue, total_duration\n\n\ndef _track(track_id, disc, track_no):\n    return Track(track_id, track_id, "artist", 100, disc=disc, track_no=track_no)\n\n\ndef test_disc_one_plays_in_full_before_disc_two():\n    tracks = [_track("d2t1", 2, 1), _track("d1t2", 1, 2), _track("d1t1", 1, 1)]\n    assert [t.track_id for t in album_order(tracks)] == ["d1t1", "d1t2", "d2t1"]\n\n\ndef test_track_numbers_order_within_a_disc():\n    tracks = [_track("t3", 1, 3), _track("t1", 1, 1), _track("t2", 1, 2)]\n    assert [t.track_id for t in album_order(tracks)] == ["t1", "t2", "t3"]\n\n\ndef test_skipping_removes_without_reordering():\n    tracks = [_track("a", 1, 1), _track("b", 1, 2), _track("c", 2, 1)]\n    assert [t.track_id for t in build_queue(tracks, skip_ids={"b"})] == ["a", "c"]\n\n\ndef test_total_duration_sums_the_tracks():\n    tracks = [_track("a", 1, 1), _track("b", 1, 2)]\n    assert total_duration(tracks) == 200\n'

def _repo_root() -> Path:
    return Path(playlist.__file__).resolve().parents[2]


def _run(defective: bool) -> subprocess.CompletedProcess:
    root = _repo_root()
    pass  # the sample is written into the copy below
    tmp = Path(tempfile.mkdtemp(prefix="agent-tests-"))
    work = tmp / "repo"
    shutil.copytree(
        root,
        work,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )
    (work / TEST_REL).parent.mkdir(parents=True, exist_ok=True)
    (work / TEST_REL).write_text(SAMPLE)
    if defective:
        for rel, content in DEFECTIVE.items():
            (work / rel).write_text(content)
    env = {**os.environ, "PYTHONPATH": str(work / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(work / TEST_REL)],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_tests_pass_on_the_correct_code():
    result = _run(defective=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_tests_fail_on_the_defective_code():
    result = _run(defective=True)
    assert result.returncode != 0, "the tests pass on defective code: they do not pin the behaviour"
