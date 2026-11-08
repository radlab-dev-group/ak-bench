---
id: INC-2911
severity: medium
module: snapshot
kind: a different window
tags: protocol, snapshot
---

# INC-2911: the image chooses its own inclusive boundary

A snapshot decides what it contains by the clock it takes the image at, and
that decision is inclusive of the record whose number the image carries: the
image's number is the last thing *in* the image, and a snapshot that excluded
its own number would be an image that had not finished. This is the window
that is easy to confuse with the replay window, because both of them are
named by the same number and one of them is inclusive. The two windows are
the same number used twice with opposite meanings: the image takes the
record at its number, and the replay starts after it. A review that finds
the inclusive form in the snapshot module and reads it as the replay rule
will "fix" the replay to match an image that was never wrong. The snapshot
is a floor; the window that starts from it must open after the number, not
at it, and the two sentences are about different modules.
