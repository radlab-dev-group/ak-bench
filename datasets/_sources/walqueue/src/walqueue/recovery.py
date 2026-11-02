"""Recover exactly the published snapshot plus its contiguous WAL suffix."""

from .errors import CorruptStore
from .journal import Journal
from .snapshot import Snapshots
from .state import State


def recover(snapshots: Snapshots, journal: Journal) -> tuple[int, State]:
    through, state = snapshots.load()
    sequence = through
    for transaction in journal.recover(through):
        candidate = state.clone()
        try:
            candidate.apply(transaction["commands"])
        except (KeyError, TypeError, ValueError) as error:
            raise CorruptStore("invalid transaction during replay") from error
        state = candidate
        sequence = transaction["sequence"]
    return sequence, state
