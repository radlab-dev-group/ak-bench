# Disc two plays before disc one finishes

The playlist in `src/playlist` orders an album in `src/playlist/queue.py`,
and the rules it follows are documented in that module's docstring. Read
them before touching anything.

Track numbers restart on every disc. Album order is by **disc first**,
then by track number within the disc: disc 1 plays in full before disc 2
starts, whatever the track numbers say.

Today, a multi-disc album is ordered by track number across the whole
album, so disc 2's track 1 plays before disc 1's track 2.

## What to check

- `album_order` in `src/playlist/queue.py` on a multi-disc album where
  the track numbers restart.
- `build_queue` must keep the corrected order while skipping tracks.
- `total_duration` must keep producing the same numbers it produced
  before.

## Boundaries

- Do not change the track record or the duration arithmetic.
- Do not modify the repository test suite under `tests/`.
- The public API of the `playlist` package stays as it is.
- The repository's own test suite has to stay green after your change.
