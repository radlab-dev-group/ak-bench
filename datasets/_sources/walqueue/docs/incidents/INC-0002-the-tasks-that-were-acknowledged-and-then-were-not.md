---
id: INC-0002
severity: high
module: snapshot
tags: compaction, crash, ops
---

# INC-0002: the tasks that were acknowledged twice, and then not at all

## What we saw

After a power cut, a store came back missing three tasks that the client had
watched acknowledged in the minutes before the cut. The store itself was
healthy: it opened, it accepted work, it compacted. The three tasks were
simply not there, and the sequence number it reported was three lower than
the one the client had last seen. Nothing in the logs was an error. The
repository suite was green throughout, and the on-call operator's first
conclusion was that the client had not flushed its acknowledgments, because
the store was the one thing that looked perfectly fine.

## What it turned out to be

The store had been mid-compaction when the power went. The compaction had
deleted the sealed segment before the new CURRENT was written, so the old
CURRENT pointed at a snapshot that no longer had the WAL suffix to explain
the acknowledged work. The client had acknowledged correctly; the store had
eaten the tail. The client was not at fault, and the operator who wrote the
first version of this note has since moved the "what we saw" section around
to say so.

## What we changed

Compactions now publish before they prune, and the crash matrix — each crash
point, a restart, a further compaction, a second restart — is a test, because
a compaction that runs to completion never shows this. The decision record
is written about the symptom — acknowledged work that is gone with no error
— and not about the step this note names.

## Read next

INC-0003 for the store that would not open for a different reason, and the
decision record that says the WAL is pruned only after CURRENT names the
snapshot.
