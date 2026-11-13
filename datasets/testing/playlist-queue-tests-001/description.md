# Write tests that pin the disc-first album order

`src/playlist/queue.py` orders an album disc-first: disc 1 plays in
full before disc 2 starts, whatever the track numbers say. Write a
pytest suite for it in `tests/test_queue_agent.py` that would catch the
ordering being flipped.

The suite will be run three times, against three copies of the
repository:

1. **as it is** — it must pass;
2. **reformatted** — the same code with comments and blank lines added,
   and nothing else; it must still pass. A suite that hashes the
   sources, or compares them with a snapshot, fails here: a comment
   changed the bytes, not the behaviour;
3. **with one behaviour changed** — the one that sorts by track number
   before disc; it must fail.

Write at least three test functions, and test behaviour: do not import
`hashlib`, `inspect`, `filecmp`, `difflib`, `dis` or `marshal`, and do not
read the files under `src/`.

Cover at least:

- disc 2 track 1 after disc 1's last track, not after disc 1 track 1;
- track numbers ordering within a disc;
- skipping removing tracks without reordering;
- the total duration.

## Boundaries

- Write the tests in `tests/test_queue_agent.py`; do not modify `src/` or
  the existing tests under `tests/`.
- Do not add third-party dependencies.
