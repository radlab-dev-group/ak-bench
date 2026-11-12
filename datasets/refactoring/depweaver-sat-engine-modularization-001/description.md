# One algorithm, six hundred lines, four jobs

`src/depweaver/solver.py` is the whole CDCL engine: the trail, the two watched
literals, the first-UIP conflict analysis, the activity heuristic, the encoding
of the version problem, and the loop that drives them. The file says why it is
one file — the trail is what the analysis reads, the watcher is what writes it,
the activities are bumped by both — and it is right that they are one algorithm.
It is not right that they are one file, because the file cannot be reviewed, and
"which part decided this" has an answer of "somewhere between line 90 and line
600".

## What to build

Split the engine into modules, each one thing:

- the **trail**: the stack of assignments, their levels, their reasons, and
  rolling it back;
- the **watched literals**: the watch lists and unit propagation to a fixpoint;
- the **conflict analysis**: walking reasons backwards to the first UIP, and
  minimising the clause that comes out;
- the **heuristic**: the activities, the bump, the rescale, and the decision;
- the **engine**: the loop, and nothing else;
- the **encoding**: the version problem into clauses.

`src/depweaver/solver/` becomes a package whose `__init__.py` exports exactly
what `solver.py` exports today, so

```python
from depweaver.solver import Activities, Solver, Trail, Watchers, encode, resolve
```

keeps working — `tests/test_solver.py` does exactly that import, and the
repository suite is the behaviour you are preserving. No module of the engine
may import one that imports it back; if two want each other, the thing they
both want belongs in a third module.

## What must not change

**The search path, not just the answer.** A SAT solver that takes a different
path can return a satisfiable for the same problem and still be a different
program, and it is the path that decides which lockfile a real resolution
picks. `docs/sat-solver-architecture.md` states the three rules that keep the
path reproducible — variables numbered in sorted `(package, version)` order,
every scan over an ordered container, ties broken by descending variable
number — and the golden tests check them directly:

- for twenty dependency graphs, `resolve()` returns the same lockfile;
- for ten encodings, `Solver.trace()` is the same list of decisions and
  implications, line for line, and so are `conflicts`, `decisions`,
  `propagations`, `learned_count` and `learnings()`.

`python -m pytest tests/` stays green. Replacing an ordered container with a
`set` where the order decides something is the classic way to pass every one of
those tests on your machine and fail them on another.
