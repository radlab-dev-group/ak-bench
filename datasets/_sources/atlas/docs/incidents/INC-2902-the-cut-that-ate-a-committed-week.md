---
id: INC-2902
severity: high
module: durability
kind: the rule behind a rule
tags: protocol, read-first
---

# INC-2902: the cut that ate a committed week

A tail was torn, and the repair cut back to the last place a transaction had
started. That is a cut, and it is the wrong one. Everything before the damage
had already been promised to a caller — a commit had been written for it, and
a promise made by a durable commit is not undone by damage further along the
file. The repair goes to the end of the last thing that could be read, and
stops. The damaged remainder goes; the promised remainder stays. A repair that
eats a committed transaction is a data-loss bug wearing the clothes of a
recovery feature, and the test for it is to write two transactions, tear the
second, and insist the first is still there.
