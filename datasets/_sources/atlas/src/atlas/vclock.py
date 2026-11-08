"""Version vectors and the documented conflict resolution of the store.

Every write in Atlas carries a version vector: a mapping from a writer node
identifier to a monotonic counter. A vector ``a`` *happens before* ``b`` when
``a`` is pointwise no greater than ``b`` and strictly smaller somewhere.
Vectors that do not order are concurrent, and concurrency is resolved
deterministically so that every replica holding the same set of candidates
chooses the same winner.

The tie-break rule is part of the wire contract, not an implementation
detail: **concurrent writers are ordered by descending node identifier, and
the candidate with the greatest node identifier wins**. Ties are impossible
because node identifiers are unique within a membership epoch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Self

from .errors import ReadRepairConflictError

BEFORE = -1
EQUAL = 0
AFTER = 1


@dataclass(frozen=True, order=True)
class VersionVector:
    """An immutable version vector keyed by writer node identifier.

    Vectors compare by ``(total counter, size, tuple of sorted items)`` so
    that they are usable as dictionary keys and sortable, which is what the
    repair path relies on. The ordering of the dataclass is *not* the happens
    before relation; use :func:`compare` for that.
    """

    counters: tuple[tuple[str, int], ...] = ()

    @classmethod
    def new(cls, counters: Mapping[str, int] | Iterable[tuple[str, int]] = ()) -> Self:
        if isinstance(counters, Mapping):
            items = [(str(name), int(value)) for name, value in counters.items() if value > 0]
        else:
            items = [(str(name), int(value)) for name, value in counters if value > 0]
        return cls(tuple(sorted(items)))

    @classmethod
    def single(cls, node: str, counter: int = 1) -> Self:
        return cls.new({node: counter})

    @property
    def as_map(self) -> dict[str, int]:
        return dict(self.counters)

    @property
    def total(self) -> int:
        return sum(value for _, value in self.counters)

    def get(self, node: str) -> int:
        for name, value in self.counters:
            if name == node:
                return value
        return 0

    def increment(self, node: str) -> Self:
        merged = self.as_map
        merged[node] = merged.get(node, 0) + 1
        return type(self).new(merged)

    def merge(self, other: Self) -> Self:
        merged = self.as_map
        for name, value in other.as_map.items():
            merged[name] = max(merged.get(name, 0), value)
        return type(self).new(merged)

    def dominates(self, other: Self) -> bool:
        """True when every counter of ``other`` is present here with a value >= its own.

        A vector dominates itself; use :meth:`compare` to tell equality from a
        strict causal advance.
        """

        for name, value in other.counters:
            if self.get(name) < value:
                return False
        return True

    def is_concurrent_with(self, other: Self) -> bool:
        return compare(self, other) == 2

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return bool(self.counters)

    def render(self) -> str:
        return "{" + ",".join(f"{name}:{value}" for name, value in self.counters) + "}"


def compare(left: VersionVector, right: VersionVector) -> int:
    """Return BEFORE, EQUAL, AFTER or 2 for concurrent."""

    left_map = left.as_map
    right_map = right.as_map
    greater = False
    lesser = False
    for name in set(left_map) | set(right_map):
        low = left_map.get(name, 0)
        high = right_map.get(name, 0)
        if low > high:
            greater = True
        elif low < high:
            lesser = True
    if greater and lesser:
        return 2
    if greater:
        return AFTER
    if lesser:
        return BEFORE
    return EQUAL


def happens_before(left: VersionVector, right: VersionVector) -> bool:
    return compare(left, right) == BEFORE


def resolve(
    candidates: Iterable[tuple[VersionVector, object]],
    *,
    equal_is_conflict: bool = False,
) -> tuple[VersionVector, object]:
    """Choose the winner among candidate versions of one key.

    A version that dominates all others wins outright. When two candidates are
    concurrent the documented tie-break applies: the candidate with the
    greatest node identifier among the vectors that contributed to the
    conflict wins. ``equal_is_conflict`` makes identical vectors an error
    instead of silently keeping the first one, which is what read repair asks
    for when two replicas report the same version through different paths.
    """

    options = list(candidates)
    if not options:
        raise ReadRepairConflictError("<none>", None, None)
    if len(options) == 1:
        return options[0]

    best_vector, best_value = options[0]
    for vector, value in options[1:]:
        relation = compare(best_vector, vector)
        if relation == BEFORE:
            best_vector, best_value = vector, value
        elif relation == AFTER:
            continue
        elif relation == EQUAL:
            if equal_is_conflict:
                raise ReadRepairConflictError("unknown", best_vector.counters, vector.counters)
            continue
        else:
            if tie_break_key(vector) > tie_break_key(best_vector):
                best_vector, best_value = vector, value
    return best_vector, best_value


def tie_break_key(vector: VersionVector) -> str:
    """The documented concurrency tie-break: greatest node identifier wins.

    The identifier considered is the largest node name that the vector has
    ever incremented, because a concurrent write always carries its own
    identifier as the writer that made it distinct.
    """

    if not vector.counters:
        return ""
    return max(name for name, _ in vector.counters)


def merge_all(vectors: Iterable[VersionVector]) -> VersionVector:
    result = VersionVector.new()
    for vector in vectors:
        result = result.merge(vector)
    return result
