"""Playing an album in order.

The rules:

1. Album order is by disc first, then by track number within the disc,
   then by track id. Disc 1 plays in full before disc 2 starts, whatever
   the track numbers say.
2. A queue is the album order with skipped tracks removed. Skipping never
   reorders what remains.
3. The total duration is the sum of the track durations, in seconds.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

from playlist.model import Track


def album_order(tracks: Iterable[Track]) -> list[Track]:
    """The tracks in album order, under the rules above."""
    return sorted(tracks, key=lambda track: (track.disc, track.track_no, track.track_id))


def build_queue(
    tracks: Iterable[Track], *, skip_ids: Collection[str] = ()
) -> list[Track]:
    """The album order without the skipped tracks."""
    skip = set(skip_ids)
    return [track for track in album_order(tracks) if track.track_id not in skip]


def total_duration(tracks: Iterable[Track]) -> int:
    """The sum of the track durations, in seconds."""
    return sum(track.duration for track in tracks)
