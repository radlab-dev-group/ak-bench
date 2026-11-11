"""Building a mix that fills a target length. The rules are in this
docstring; the implementation is the task.

``build_mix(tracks, target_seconds, *, tolerance=0)`` selects tracks
greedily — it is not an optimal subset-sum search, and the greedy order
below is the contract:

1. Candidates are considered longest first: by ``duration`` descending,
   ties by ``track_id`` ascending.
2. A candidate is selected when both hold: its artist has not been
   selected yet (at most one track per artist, compared exactly), and
   adding it keeps the running total at or below ``target_seconds``. The
   mix never exceeds the target.
3. After the walk, if the selected total is less than
   ``target_seconds - tolerance``, no mix good enough was found and the
   result is an empty list. Otherwise the selected tracks are returned
   sorted by ``(artist, title, track_id)`` ascending.

``target_seconds`` must be positive and ``tolerance`` must not be negative;
anything else raises :class:`ValueError`. An empty track list returns an
empty list.
"""

from __future__ import annotations

from collections.abc import Iterable

from playlist.model import Track


def build_mix(
    tracks: Iterable[Track], target_seconds: int, *, tolerance: int = 0
) -> list[Track]:
    """Return the greedy mix under the rules in this module."""
    raise NotImplementedError("build_mix is specified in this module and not yet written")
