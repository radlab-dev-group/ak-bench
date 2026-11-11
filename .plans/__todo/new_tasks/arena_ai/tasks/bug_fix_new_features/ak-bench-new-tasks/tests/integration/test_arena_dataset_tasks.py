"""Integrity proofs for the Arena-authored easy/medium/hard tasks.

Five new fixtures (``timetable``, ``quiz``, ``garden``, ``playlist``,
``cachekit``) each carry one bug-fix and one new-feature task. A bug-fix
task is only real if its mutation is verified (hidden tests pass on the
base commit and fail once the patch is applied) while the seed suite stays
green in both states. A new-feature task has no mutation, so its honesty
check is the other way round: the hidden and public tests must fail on the
base commit with ``NotImplementedError`` and pass once the specification
is implemented. The reference implementations below live only in this test
file, never inside a seed or a prepared agent workspace.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from akbench.datasets import RepositoryManager, WorkspaceManager
from akbench.datasets.dataset import Dataset
from akbench.datasets.verification import MutationVerifier, run_hidden_tests

ROOT = Path(__file__).resolve().parents[2]

BUG_FIX_TASKS = [
    "timetable-overlap-001",
    "quiz-streak-001",
    "garden-watering-001",
    "playlist-queue-001",
    "cachekit-eviction-001",
]

REFERENCE_FIND_SLOT = """from __future__ import annotations

from collections.abc import Iterable


def find_slot(
    busy: Iterable[tuple[int, int]],
    duration: int,
    window_start: int,
    window_end: int,
    gap: int = 0,
) -> int | None:
    if duration <= 0:
        raise ValueError(f"duration must be positive, got {duration}")
    if gap < 0:
        raise ValueError(f"gap cannot be negative, got {gap}")
    if window_end <= window_start:
        raise ValueError(
            f"window_end must be after window_start, got [{window_start}, {window_end})"
        )
    intervals = sorted((start, end) for start, end in busy)
    start = window_start
    while start + duration <= window_end:
        conflict_end = None
        for busy_start, busy_end in intervals:
            if start + duration <= busy_start - gap or start >= busy_end + gap:
                continue
            conflict_end = busy_end + gap
            break
        if conflict_end is None:
            return start
        start = conflict_end
    return None
"""

REFERENCE_RANK_ATTEMPTS = """from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from quiz.model import AttemptResult


@dataclass(frozen=True)
class Ranked:
    player: str
    total: int
    correct_count: int
    submitted_at: int
    rank: int


def rank_attempts(entries: Iterable[AttemptResult]) -> list[Ranked]:
    entries = list(entries)
    ordered = sorted(
        entries,
        key=lambda entry: (-entry.total, -entry.correct_count, entry.submitted_at, entry.player),
    )
    ranked = []
    for entry in ordered:
        rank = 1 + sum(
            1
            for other in entries
            if (other.total, other.correct_count) > (entry.total, entry.correct_count)
        )
        ranked.append(
            Ranked(entry.player, entry.total, entry.correct_count, entry.submitted_at, rank)
        )
    return ranked
"""

REFERENCE_PLAN_WATERING = """from __future__ import annotations

from collections.abc import Iterable

from garden.model import Plant
from garden.water import due_day


def plan_watering(
    plants: Iterable[Plant],
    *,
    start_day: int,
    horizon_days: int,
    capacity_per_day: int,
) -> dict[int, list[str]]:
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")
    if capacity_per_day <= 0:
        raise ValueError(f"capacity_per_day must be positive, got {capacity_per_day}")
    window_end = start_day + horizon_days
    due = [plant for plant in plants if due_day(plant) < window_end]
    due.sort(key=lambda plant: (max(due_day(plant), start_day), plant.plant_id))
    plan: dict[int, list[str]] = {}
    counts: dict[int, int] = {}
    for plant in due:
        for day in range(start_day, window_end):
            if counts.get(day, 0) < capacity_per_day:
                plan.setdefault(day, []).append(plant.plant_id)
                counts[day] = counts.get(day, 0) + 1
                break
    return plan
"""

REFERENCE_BUILD_MIX = """from __future__ import annotations

from collections.abc import Iterable

from playlist.model import Track


def build_mix(
    tracks: Iterable[Track], target_seconds: int, *, tolerance: int = 0
) -> list[Track]:
    if target_seconds <= 0:
        raise ValueError(f"target_seconds must be positive, got {target_seconds}")
    if tolerance < 0:
        raise ValueError(f"tolerance cannot be negative, got {tolerance}")
    candidates = sorted(tracks, key=lambda track: (-track.duration, track.track_id))
    selected: list[Track] = []
    artists: set[str] = set()
    total = 0
    for track in candidates:
        if track.artist in artists:
            continue
        if total + track.duration > target_seconds:
            continue
        selected.append(track)
        artists.add(track.artist)
        total += track.duration
    if total < target_seconds - tolerance:
        return []
    return sorted(selected, key=lambda track: (track.artist, track.title, track.track_id))
"""

REFERENCE_TTL_CACHE = """from __future__ import annotations

from collections import OrderedDict
from typing import Any


class TTLCache:
    def __init__(self, capacity: int, ttl: int) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        self._capacity = capacity
        self._ttl = ttl
        self._data: OrderedDict[Any, tuple[Any, int]] = OrderedDict()

    def get(self, key: Any, now: int) -> Any:
        if key not in self._data:
            return None
        value, expires_at = self._data[key]
        if now >= expires_at:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: Any, value: Any, now: int) -> None:
        self.purge(now)
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (value, now + self._ttl)
        while len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def purge(self, now: int) -> int:
        expired = [key for key, (_, expires_at) in self._data.items() if now >= expires_at]
        for key in expired:
            del self._data[key]
        return len(expired)

    def __len__(self) -> int:
        return len(self._data)
"""

NEW_FEATURE_TASKS = {
    "timetable-slots-001": ("src/timetable/slots.py", REFERENCE_FIND_SLOT),
    "quiz-ranking-001": ("src/quiz/ranking.py", REFERENCE_RANK_ATTEMPTS),
    "garden-plan-001": ("src/garden/plan.py", REFERENCE_PLAN_WATERING),
    "playlist-mix-001": ("src/playlist/mix.py", REFERENCE_BUILD_MIX),
    "cachekit-ttl-001": ("src/cachekit/ttl.py", REFERENCE_TTL_CACHE),
}


def suite(workspace, tests, *, passes=True):
    result = run_hidden_tests(workspace, tests)
    assert not result.errored, result.output
    assert result.passed is passes, result.output
    return result.output


@pytest.fixture
def resources(tmp_path):
    dataset = Dataset.load(ROOT / "datasets", base_dir=ROOT)
    manager = WorkspaceManager(RepositoryManager(tmp_path / "repos"), tmp_path / "workspaces")
    return dataset, manager


@pytest.mark.parametrize("task_id", BUG_FIX_TASKS)
def test_bug_fix_mutation_is_verified_and_seed_suite_survives(resources, task_id):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(task_id))
    result = MutationVerifier(manager).verify(loaded)
    assert result.ok, (result.as_dict(), result.base, result.mutated)
    assert result.verdict.value == "verified"
    for mutated in (False, True):
        prepared = manager.prepare(
            loaded.task, f"{task_id}-{mutated}", task_dir=loaded.path, apply_mutation=mutated
        )
        try:
            suite(prepared.path, prepared.path / "tests")
            suite(prepared.path, loaded.path / "public_tests", passes=not mutated)
        finally:
            manager.cleanup(prepared.path)


@pytest.mark.parametrize("task_id", sorted(NEW_FEATURE_TASKS))
def test_new_feature_is_missing_but_reference_is_complete(resources, task_id):
    dataset, manager = resources
    loaded = dataset.materialize(dataset.require(task_id))
    assert loaded.task.task.mutation is None
    prepared = manager.prepare(loaded.task, f"{task_id}-base", task_dir=loaded.path)
    try:
        assert not (prepared.path / "hidden_tests").exists()
        suite(prepared.path, prepared.path / "tests")
        output = suite(prepared.path, loaded.path / "hidden_tests", passes=False)
        assert "NotImplementedError" in output
        suite(prepared.path, loaded.path / "public_tests", passes=False)
        relative, reference = NEW_FEATURE_TASKS[task_id]
        solution = prepared.path / relative
        solution.write_text(reference, encoding="utf-8")
        suite(prepared.path, prepared.path / "tests")
        suite(prepared.path, loaded.path / "public_tests")
        suite(prepared.path, loaded.path / "hidden_tests")
    finally:
        manager.cleanup(prepared.path)
        shutil.rmtree(prepared.path, ignore_errors=True)
