"""Visible checks for the tie-break invariant. These are not the whole evidence.

They fail on a cluster that has lost the rule and pass on a correct one, and
they are deliberately less surgical than the hidden scenarios: they say which
rule broke, not which line broke it.
"""

from atlas.repair import ReadRepairer
from atlas.values import Record
from atlas.vclock import VersionVector


def _record(key, value, generation, node, lsn=0):
    return Record.put(
        key,
        value,
        generation=generation,
        vector=VersionVector.single(node, generation),
        writer=node,
        lsn=lsn,
    )


def test_concurrent_writes_resolve_to_the_greatest_writer_identifier():
    left = _record("k", "left", 1, "aaa")
    right = _record("k", "right", 1, "zzz")
    winner, _losers, by_tie = ReadRepairer.choose(ReadRepairer.__new__(ReadRepairer), [left, right])
    assert by_tie is True
    assert winner is right


def test_a_causal_winner_does_not_need_the_tie_break():
    older = _record("k", "old", 1, "zzz", lsn=1)
    newer = _record("k", "new", 2, "zzz", lsn=2)
    winner, _losers, by_tie = ReadRepairer.choose(ReadRepairer.__new__(ReadRepairer), [older, newer])
    assert winner is newer
    assert by_tie is False
