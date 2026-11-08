---
id: INC-2901
severity: high
module: recovery
kind: the rule behind a rule
tags: protocol, read-first
---

# INC-2901: the window opens after the number not at it

The replay started one record too early and nobody noticed for a fortnight,
because the record it replayed was one that had already been folded into the
image. The number in the header of an image is the number of the last thing it
*contains*, and a window that starts at that number replays it a second time.
For a row holding a count that is not harmless: the second application is
arithmetically valid, checksum-clean, and wrong. Ask for what came after the
number, always, and if a deployment ever says otherwise, say it in exactly one
place so there is one place to look.
