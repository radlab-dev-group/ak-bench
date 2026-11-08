---
id: INC-2903
severity: high
module: fencing
kind: the rule behind a rule
tags: protocol, read-first
---

# INC-2903: the token that matched by accident

A drained worker acked work it had not finished, because the comparison let a
number through that was merely not-behind. Tokens are not progress bars. The
number a caller holds either is the one the store is holding at this moment or
it is not, and anything else means the caller has seen something the store has
not, which is the same category of wrong as being behind. Being behind is the
drained worker; being ahead is the one that has already been replaced and is
still talking. Refuse both, and refuse the epoch before you refuse the number,
because a caller from an epoch that has ended is not late, it is gone.
