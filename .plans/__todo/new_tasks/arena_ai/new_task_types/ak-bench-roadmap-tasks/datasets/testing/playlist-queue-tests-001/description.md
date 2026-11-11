# Write tests that pin the disc-first album order

`src/playlist/queue.py` orders an album disc-first: disc 1 plays in
full before disc 2 starts, whatever the track numbers say. Write a
pytest suite for it in `tests/test_queue_agent.py` that would catch the
ordering being flipped.

The suite will be run twice: once against the code as it is (it must
pass) and once against a variant that sorts by track number before
disc (it must fail). Cover at least:

- disc 2 track 1 after disc 1's last track, not after disc 1 track 1;
- track numbers ordering within a disc;
- skipping removing tracks without reordering;
- the total duration.

## Boundaries

- Write the tests in `tests/test_queue_agent.py`; do not modify `src/` or
  the existing tests under `tests/`.
- Do not add third-party dependencies.
