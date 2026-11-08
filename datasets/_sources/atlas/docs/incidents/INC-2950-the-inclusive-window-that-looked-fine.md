---
id: INC-2900
severity: high
module: recovery
kind: a fix we reverted
tags: protocol, read-first
---

# INC-2900: the inclusive window that looked fine

We made the replay window inclusive of the image's own number, and for three
weeks it looked like an improvement: fewer records were skipped on open, and
the open got faster. It was wrong on the first counter that was incremented
twice. The inclusive form is not "more conservative" — it re-applies work that
has been done. This note is here because the change is tempting and because
the reverted commit is still in the history, and whoever finds it should read
the note titled *the window opens after the number, not at it* before
reproducing it.
