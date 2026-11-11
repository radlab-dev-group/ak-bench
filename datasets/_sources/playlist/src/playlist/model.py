"""The track record."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    """One track on an album.

    ``disc`` and ``track_no`` locate the track on its album. Track numbers
    restart on every disc: disc 2 has its own track 1, which follows disc
    1's last track, not disc 1's track 1.
    """

    track_id: str
    title: str
    artist: str
    duration: int
    disc: int = 1
    track_no: int = 1

    def __post_init__(self) -> None:
        if not self.track_id:
            raise ValueError("a track needs an id")
        if self.duration <= 0:
            raise ValueError(f"duration must be positive, got {self.duration}")
        if self.disc < 1:
            raise ValueError(f"disc must be at least 1, got {self.disc}")
        if self.track_no < 1:
            raise ValueError(f"track_no must be at least 1, got {self.track_no}")
