---
id: INC-2900
severity: high
module: recovery
kind: the rule behind a rule
tags: protocol, read-first
---

# INC-2900: the authoritative copy was the one nobody published

The replica came back with two snapshot files in its directory and adopted
the newer one. It should not have. Adoption is not recovery: what recovery
does is read the pointer file and ask for the image it names, and the pointer
is the record of the decision the process made before it died. A file sitting
in the same directory is not a decision, it is a file — it may have been
written by a run that crashed between writing and committing, and a recovery
that reads it is inventing a publication the cluster never agreed to. The
older image, named by the pointer, is the state of the world. Everything else
in that directory is debris, including the debris that looks newer.
