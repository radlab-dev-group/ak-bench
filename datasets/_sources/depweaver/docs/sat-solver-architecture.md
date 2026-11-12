# The CDCL engine: what it is and why it is one file

`src/depweaver/solver.py` is a conflict-driven clause learning solver. It
exists for one reason: the version problem is a satisfaction problem, and a
CDCL solver answers satisfaction problems that the package's resolver answers
only the easy way.

## The pieces, and the dependency between them

The module has four structures, and each one exists because of another:

* **`Trail`** — the stack of assignments. An assignment is a decision or a
  propagation; a propagation carries the clause that implied it, because the
  next piece needs exactly that clause.
* **`Watchers`** — two watched literals per clause. A clause is read only when
  one of its watches goes false; that is the entire cost model, and it is the
  reason the propagation in `Solver.propagate` is the only code that moves a
  watch.
* **`Activities`** — a variable's blame score. Bumped by the conflict
  analysis, consulted by the decision loop. It is the memory that makes the
  next search different from the last one.
* **`Solver`** — the loop. It propagates, and when propagation reports a
  refuted clause it analyses it: `analyze` walks the implication graph back to
  the first unique implication point, `minimize` drops body literals the
  clause already implies, and the surviving clause is learned and the search
  backjumps to the level that clause still asserts at.

The trail is what `analyze` reads, the watcher is what writes the trail, and
the activities are bumped by both. That is why the file is one: split the
trail from the analysis and the analysis has no reason clauses; split the
watcher from the propagation and the propagation has nothing to watch.

## Determinism, and the three rules that keep it

The answer to the same input must be the same answer on every machine, or the
lockfile is not a lockfile. Three rules enforce it:

1. **Variables are numbered in sorted `(package, version)` order.** The
   numbering is a function of the input, not of the order releases were
   registered. `encode` is the only place variables get numbers.
2. **Every scan is over a sorted or explicitly ordered container.** The
   propagation walks clause positions, the analysis walks the trail, the
   encoding walks sorted package names. A `set` in the middle of one of those
   walks is a different answer on a different machine, and the tests treat
   that as a bug.
3. **Ties break by descending variable number.** `Activities.decide` is the
   only place a choice is made between equal activities, and it is a total
   order: the highest variable number wins, never the first one the
   dictionary happened to return.

## The interface a refactor must keep

`Solver(clauses, variables=n)` then `.solve()` is the public shape: in, a
problem; out, a truth value, a model from `.model()`, a trail from `.trace()`,
and the learned clauses from `.learnings()`. A split of the module may move
`Trail`, `Watchers` and `Activities` into their own files, and may give
`Solver` a constructor that takes them as collaborators, but it may not change
what `solve()` does or what the answer is, because the behaviour these tests
pin down is the behaviour the lockfile depends on.

The preference rule is a second, separate interface: `resolve(packages,
requirements)` returns the highest version of every package that the
requirements allow, packages considered in name order and versions from the
top of their domain down. That rule is documented here, not in the clauses —
the clauses say what is possible, and the search plus the unit clauses it
accumulates say what is chosen.
