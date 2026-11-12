"""A conflict-driven clause learning solver over the version problem.

The dependency problem is a satisfaction problem. Every release that can
appear in a solution becomes a boolean: ``pick`` says the release is selected
for its package, ``ok`` says it satisfies every range currently active for
that package. Requirements, the one-version-per-package rule and the
eligibility rules become clauses, and a satisfying assignment is a lockfile.

This module holds the whole engine in one file: the decision trail, the
two-watched-literal propagation, the conflict analysis that learns a clause
and jumps back, the activity heuristic that decides what to try next, and the
encoding of the version problem into clauses. They are one file because they
are one algorithm — the trail is what the analysis reads, the watcher is what
writes the trail, and the activities are bumped by both — and reading the
propagation without the analysis explains nothing about why it restarts where
it does.

Determinism is the property everything else here depends on. A solver whose
answer depends on hash ordering produces a different lockfile on a different
machine, which is worse than a slow solver. Three rules keep it reproducible:

* variables are numbered in sorted ``(package, version)`` order, so the
  numbering is a function of the input and not of insertion order;
* every scan over clauses, literals and packages is over a sorted or
  explicitly ordered container, never over a set;
* the decision heuristic breaks ties by descending variable number, never by
  dictionary order.

Two runs on the same input produce the same trail, the same learned clauses,
the same number of conflicts, and the same answer.
"""

from __future__ import annotations

from typing import Iterable, Sequence

#: A literal is a non-zero integer: ``var`` positive means the variable is
#: true, ``-var`` means it is false. Variable 0 is not used.
Literal = int

#: A clause is a tuple of literals, satisfied when any one of them is true.
#: The empty clause is the contradiction.
Clause = tuple[Literal, ...]


class Trail:
    """The stack of assignments, with the index that makes them lookup-able.

    An assignment is either a *decision* — made by the heuristic, with no
    reason — or a *propagation*, whose reason is the clause that became unit
    when it was made. Conflict analysis walks reasons backwards, which is why
    the reason is stored with the assignment instead of being reconstructed.
    """

    def __init__(self) -> None:
        self.literals: list[Literal] = []
        self.reasons: dict[Literal, Clause] = {}
        self.levels: dict[Literal, int] = {}
        self.positions: dict[int, int] = {}

    def __len__(self) -> int:
        return len(self.literals)

    @property
    def level(self) -> int:
        """The level of the deepest assignment, or 0 when the trail is empty."""

        if not self.literals:
            return 0
        return self.levels[self.literals[-1]]

    def value(self, literal: Literal) -> bool | None:
        """True, False or None: whether ``literal`` holds on the trail."""

        variable = abs(literal)
        if variable not in self.positions:
            return None
        assigned = self.literals[self.positions[variable]] > 0
        return assigned if literal > 0 else not assigned

    def assigned(self, variable: int) -> bool:
        return variable in self.positions

    def assignment_of(self, variable: int) -> Literal:
        return self.literals[self.positions[variable]]

    def assign(self, literal: Literal, level: int, reason: Clause | None = None) -> None:
        variable = abs(literal)
        if variable in self.positions:
            raise ValueError(f"variable {variable} is already assigned")
        self.positions[variable] = len(self.literals)
        self.literals.append(literal)
        self.levels[literal] = level
        if reason is not None:
            self.reasons[literal] = reason

    def reason_for(self, variable: int) -> Clause | None:
        return self.reasons.get(self.assignment_of(variable))

    def level_of(self, variable: int) -> int:
        return self.levels[self.assignment_of(variable)]

    def position_of(self, variable: int) -> int:
        return self.positions[variable]

    def assignment_at(self, position: int) -> Literal:
        return self.literals[position]

    def rollback(self, to_level: int) -> list[Literal]:
        """Undo every assignment above ``to_level`` and return them in order.

        The search does not need the undone literals; a trace and a test do.
        The shape of a backjump is as observable as the answer, and it is the
        thing a refactoring is most likely to change by accident.
        """

        undone: list[Literal] = []
        while self.literals and self.levels[self.literals[-1]] > to_level:
            literal = self.literals.pop()
            del self.positions[abs(literal)]
            del self.levels[literal]
            self.reasons.pop(literal, None)
            undone.append(literal)
        return undone

    def decisions(self) -> list[tuple[int, Literal]]:
        """The decisions in trail order, as ``(level, literal)`` pairs."""

        return [
            (self.levels[literal], literal)
            for literal in self.literals
            if literal not in self.reasons
        ]


class Watchers:
    """Two watched literals per clause.

    A clause is examined only when one of its watched literals is assigned
    false. Until then the clause is neither unit nor refuted and the solver
    never looks at it — that is the whole point, and the reason a SAT solver
    scales where naive unit propagation does not.

    The invariant: a clause watches the literals at positions 0 and 1, and an
    unsatisfied clause never has a false literal under its watch unless it is
    unit. Maintenance happens in :meth:`Solver.propagate`, the only place a
    watch moves; buckets are keyed by the watched literal, so the clause is
    found in ``buckets[literal]`` for each of its two watches.
    """

    def __init__(self) -> None:
        self.buckets: dict[Literal, list[int]] = {}

    def watch(self, literal: Literal, identifier: int) -> None:
        self.buckets.setdefault(literal, []).append(identifier)

    def watching(self, literal: Literal) -> list[int]:
        return self.buckets.get(literal, [])

    def take(self, literal: Literal) -> list[int]:
        """Remove and return the watchers of ``literal``.

        Propagation swaps the bucket out once and puts back only the clauses
        that still need this watch, which keeps the list it walks stable while
        it walks.
        """

        return self.buckets.pop(literal, [])

    def counts(self) -> dict[Literal, int]:
        return {literal: len(ids) for literal, ids in sorted(self.buckets.items())}


class Activities:
    """Variable activity: the memory of what has been to blame lately.

    A variable named by a conflict is bumped, and the increment is rescaled
    before it can overflow. The decision picks the unassigned variable with
    the greatest activity, sending the search back near the region that just
    failed — which is what makes clause learning beat chronological
    backtracking on the instances that matter.
    """

    def __init__(self, decay: float = 0.95) -> None:
        if not 0.0 < decay < 1.0:
            raise ValueError("activity decay must be inside (0, 1)")
        self.decay = decay
        self.values: dict[int, float] = {}
        self._increment = 1.0
        self._limit = 1.0e20

    def of(self, variable: int) -> float:
        return self.values.get(variable, 0.0)

    def bump(self, variables: Iterable[int]) -> None:
        for variable in variables:
            self.values[variable] = self.values.get(variable, 0.0) + self._increment
        if self._increment > self._limit:
            self.rescale()

    def rescale(self) -> None:
        factor = 1.0 / self._limit
        for variable in list(self.values):
            self.values[variable] *= factor
        self._increment *= factor

    def decide(self, candidates: Iterable[int]) -> int | None:
        """The candidate with the greatest activity, ties by highest variable.

        A tie broken by dictionary or heap order would make the answer depend
        on the order clauses were added in: the determinism this module
        promises is the first thing a careless refactoring takes away.
        """

        best: int | None = None
        best_activity = 0.0
        for variable in sorted(candidates, reverse=True):
            activity = self.of(variable)
            if best is None or activity > best_activity:
                best, best_activity = variable, activity
        return best


class Solver:
    """CDCL with watched literals, first-UIP learning and activity decisions.

    ``clauses`` is the problem; the solver never rewrites it. Learned clauses
    go after the input ones, so ``clauses[:input_count]`` is always the
    problem exactly as it was handed over, and ``learned_count`` says how much
    the search added to it.
    """

    def __init__(
        self,
        clauses: Iterable[Clause] = (),
        *,
        decay: float = 0.95,
        variables: int | None = None,
    ) -> None:
        self.clauses: list[Clause] = []
        self.input_count = 0
        self.watchers = Watchers()
        self.trail = Trail()
        self.activities = Activities(decay)
        self.conflicts = 0
        self.decisions = 0
        self.propagations = 0
        self.learned_count = 0
        #: Set when a clause is refuted the moment it is added — a unit clause
        #: whose literal is already false, or the empty clause. It is a fact
        #: about the input rather than about the search, so it outlives
        #: :meth:`solve` and gives every later answer the same: unsatisfiable.
        self.refuted = False
        self._queue = 0
        self._level = 0
        self.variables = variables or 0
        for clause in clauses:
            self.add_clause(clause)
        self.input_count = len(self.clauses)
        if variables is None:
            self.variables = max(
                (abs(literal) for clause in self.clauses for literal in clause), default=0
            )

    # -- construction ------------------------------------------------------

    def add_clause(self, clause: Clause, *, learned: bool = False) -> int:
        """Store a clause and watch its first two literals.

        A unit clause is assigned at level 0 rather than watched: there is
        nothing to watch in a one-literal clause, and propagating it now is
        what an eager solver should do. A clause already satisfied by the
        trail is stored and left alone; a clause already refuted marks the
        whole problem refuted, because nothing downstream can undo that.
        """

        identifier = len(self.clauses)
        row = tuple(clause)
        self.clauses.append(row)
        for literal in row:
            self.variables = max(self.variables, abs(literal))
        if learned:
            self.learned_count += 1
        if not row:
            self.refuted = True
            return identifier
        if len(row) == 1:
            value = self.trail.value(row[0])
            if value is False:
                self.refuted = True
            elif value is None:
                self.trail.assign(row[0], 0, row)
            return identifier
        self.watchers.watch(row[0], identifier)
        self.watchers.watch(row[1], identifier)
        return identifier

    # -- reading -----------------------------------------------------------

    def value(self, literal: Literal) -> bool | None:
        return self.trail.value(literal)

    def satisfied(self, clause: Clause) -> bool:
        return any(self.trail.value(literal) is True for literal in clause)

    def model(self) -> dict[int, bool]:
        """Every assigned variable and the truth it was given."""

        return {
            variable: self.trail.assignment_of(variable) > 0
            for variable in sorted(self.trail.positions)
        }

    def trace(self) -> list[str]:
        """The trail as lines: decisions and propagations, in order.

        A trace is how a test says "the same search happened" instead of "some
        answer came out", which is the difference between checking a solver and
        watching one get lucky.
        """

        lines: list[str] = []
        for position, literal in enumerate(self.trail.literals):
            level = self.trail.levels[literal]
            reason = self.trail.reasons.get(literal)
            if reason is None:
                lines.append(f"{position:04d} L{level} decide {literal}")
            else:
                body = ",".join(str(item) for item in reason)
                lines.append(f"{position:04d} L{level} imply {literal} <- ({body})")
        return lines

    # -- propagation -------------------------------------------------------

    def propagate(self) -> Clause | None:
        """Unit propagation to a fixpoint; ``None``, or the refuting clause.

        Only the watchers of a literal that has just become false are read. A
        watched clause then either keeps its watch (its other watched literal
        is already true), moves its watch to any other literal of its own that
        is still open, or has nowhere to go: it is unit, and assigns that last
        literal with itself as the reason. A clause with both watches false
        and nothing else true is refuted, and is returned whole — the search
        does not interpret it, analysis does.
        """

        while self._queue < len(self.trail):
            decided = self.trail.assignment_at(self._queue)
            self._queue += 1
            self.propagations += 1
            watchers = self.watchers.take(-decided)
            keep: list[int] = []
            index = 0
            while index < len(watchers):
                identifier = watchers[index]
                index += 1
                clause = self.clauses[identifier]
                if clause[0] == -decided:
                    clause = (clause[1], clause[0]) + clause[2:]
                    self.clauses[identifier] = clause
                # Position 1 now holds the literal that just became false.
                if self.trail.value(clause[0]) is True:
                    keep.append(identifier)
                    continue
                moved = False
                for position in range(2, len(clause)):
                    if self.trail.value(clause[position]) is not False:
                        clause = (
                            (clause[0], clause[position])
                            + clause[1:position]
                            + clause[position + 1 :]
                        )
                        self.clauses[identifier] = clause
                        self.watchers.watch(clause[1], identifier)
                        moved = True
                        break
                if moved:
                    continue
                # Nowhere left to watch: the clause stays where it is.
                keep.append(identifier)
                if self.trail.value(clause[0]) is False:
                    keep.extend(watchers[index:])
                    self.watchers.buckets[-decided] = keep
                    self._queue = len(self.trail)
                    return clause
                self.trail.assign(clause[0], self._level, clause)
            self.watchers.buckets[-decided] = keep
        return None

    # -- conflict analysis -------------------------------------------------

    def analyze(self, conflict: Clause) -> tuple[Clause, int]:
        """First-UIP analysis: the clause to learn, and the level to jump to.

        The implication graph is walked backwards from the conflict — each
        assigned literal replaced by the clause that implied it — until the
        unexplained literals on the current level number exactly one. That one
        is the unique implication point: it alone implies everything else the
        search did at this level, so its negation together with the surviving
        lower-level literals is a clause the conflict entails. The search
        resumes at the highest level still present in the body, which is the
        non-chronological part of the name.

        An empty learned clause is the contradiction at level 0: the input,
        not the choices, is unsatisfiable.
        """

        seen: set[int] = set()
        learnt: list[Literal] = [0]
        path = 0
        index = len(self.trail) - 1
        clause = conflict
        point: Literal | None = None
        while True:
            for literal in clause if point is None else clause[1:]:
                variable = abs(literal)
                if variable in seen:
                    continue
                if self.trail.level_of(variable) == 0:
                    continue
                seen.add(variable)
                if self.trail.level_of(variable) >= self._level:
                    path += 1
                else:
                    learnt.append(literal)
            while index >= 0 and abs(self.trail.assignment_at(index)) not in seen:
                index -= 1
            if index < 0:
                return (), 0
            point = self.trail.assignment_at(index)
            index -= 1
            seen.discard(abs(point))
            path -= 1
            if path <= 0:
                learnt[0] = -point
                break
            reason = self.trail.reason_for(abs(point))
            if reason is None:
                # A decision with literals still unexplained: the decision is
                # the implication point of its own level.
                learnt[0] = -point
                break
            clause = reason
        self.activities.bump(seen | {abs(point)})
        learnt = list(self.minimize(tuple(learnt)))
        if len(learnt) == 1:
            return tuple(learnt), 0
        pivot = 1
        deepest = self.trail.level_of(abs(learnt[1]))
        for position in range(2, len(learnt)):
            level = self.trail.level_of(abs(learnt[position]))
            if level > deepest:
                pivot, deepest = position, level
        learnt[1], learnt[pivot] = learnt[pivot], learnt[1]
        return tuple(learnt), deepest

    def minimize(self, clause: Clause) -> Clause:
        """Drop a body literal whose reason the clause already contains.

        Self-subsuming resolution: when every literal that implied ``b`` is
        itself in the clause, ``b`` carries nothing the clause did not already
        say, and removing it leaves a clause that is shorter and stronger. Only
        literals already in the clause may stand in for the reason, so what
        comes out is still a consequence of the same conflict.
        """

        present = set(clause)
        keep: list[Literal] = [clause[0]]
        for literal in clause[1:]:
            reason = self.trail.reason_for(abs(literal))
            if reason is not None:
                # The reason names the literal it implied first; what is left
                # is what that literal was inferred from.
                implied = set(reason) - {reason[0]}
                if implied and implied <= present:
                    continue
            keep.append(literal)
        return tuple(keep)

    # -- the search --------------------------------------------------------

    def solve(self, *, budget: int | None = None) -> bool:
        """Search for a model. ``True`` when the clauses are satisfiable.

        A decision is always positive: the search tries "pick this release"
        before "do not pick it", and learning is what turns a wrong positive
        into a clause that keeps it wrong forever after. A conflict whose
        analysis learns nothing is the contradiction at level 0, and a conflict
        at level 0 is the only way this search can answer no.
        """

        if self.refuted:
            return False
        self.trail.rollback(0)
        self._queue = 0
        self._level = 0
        while True:
            conflict = self.propagate()
            if conflict is not None:
                self.conflicts += 1
                learned, level = self.analyze(conflict)
                if not learned:
                    self.refuted = True
                    return False
                self.trail.rollback(level)
                # The trail is shorter than the propagation pointer now: any
                # assignment the jump undid must not be looked at again, and
                # the asserting literal below is the next thing to examine.
                self._queue = len(self.trail)
                self._level = level
                if self.trail.value(learned[0]) is None:
                    self.trail.assign(learned[0], level, learned)
                elif self.trail.value(learned[0]) is False:
                    self.refuted = True
                    return False
                self.add_clause(learned, learned=True)
                if self.refuted:
                    return False
                continue
            if budget is not None and self.decisions > budget:
                raise RecursionError("decision budget exhausted")
            variable = self.activities.decide(
                item for item in range(1, self.variables + 1) if not self.trail.assigned(item)
            )
            if variable is None:
                return True
            self.decisions += 1
            self._level = self.trail.level + 1
            self.trail.assign(variable, self._level)

    def learnings(self) -> list[Clause]:
        """The clauses the search learned, in the order it learned them."""

        return list(self.clauses[self.input_count :])


def encode(
    packages: dict[str, Sequence[tuple[str, bool]]],
    requirements: Sequence[tuple[str, Sequence[str]]],
) -> tuple[list[Clause], dict[str, dict[tuple[str, str], int]], int]:
    """Turn packages and requirements into clauses.

    ``packages`` maps a package name to ``(version, is_prerelease)`` pairs;
    ``requirements`` is a list of ``(package, versions-that-satisfy-it)``, with
    the filtering done by the caller's version logic. Returns the clauses, the
    ``pick`` and ``ok`` variable maps, and the number of variables used.

    Variables are numbered in sorted ``(package, version)`` order: the ``pick``
    variables first, then the ``ok`` ones. A requirement no version satisfies
    becomes the empty clause, which is the honest encoding of impossible.
    """

    pick: dict[tuple[str, str], int] = {}
    ok: dict[tuple[str, str], int] = {}
    number = 1
    for name in sorted(packages):
        for version, _prerelease in sorted(packages[name]):
            pick[(name, version)] = number
            number += 1
    for name in sorted(packages):
        for version, _prerelease in sorted(packages[name]):
            ok[(name, version)] = number
            number += 1
    clauses: list[Clause] = []
    # One version per package: every pair of versions excludes the other.
    for name in sorted(packages):
        variables = [pick[(name, version)] for version, _ in sorted(packages[name])]
        for index, left in enumerate(variables):
            for right in variables[index + 1 :]:
                clauses.append((-left, -right))
    # A requirement must be met by one of the versions that meet it.
    for name, versions in requirements:
        if name not in packages:
            raise KeyError(f"requirement on unknown package {name!r}")
        present = sorted(
            {version for version in versions if (name, version) in pick},
            key=lambda item: pick[(name, item)],
        )
        clauses.append(
            () if not present else tuple(pick[(name, version)] for version in present)
        )
    # Selecting a release is the same act as selecting one that is eligible.
    for (name, version), variable in sorted(pick.items(), key=lambda item: item[1]):
        marker = ok[(name, version)]
        clauses.append((-variable, marker))
        clauses.append((-marker, variable))
    return clauses, {"pick": pick, "ok": ok}, number - 1


def resolve(
    packages: dict[str, Sequence[tuple[str, bool]]],
    requirements: Sequence[tuple[str, Sequence[str]]],
    *,
    budget: int = 100_000,
) -> dict[str, str] | None:
    """The highest version of every package the requirements allow.

    Preference is not encoded in the clauses; it is imposed by asking, for
    every package in name order and from the top of its domain down, whether
    the problem is still satisfiable with that version picked. The first
    answer that holds becomes a unit clause, so later questions are asked
    against the choice already made. Packages in name order, versions from
    highest to lowest: a rule, stated once, that every run follows.
    """

    clauses, maps, count = encode(packages, requirements)
    pick = maps["pick"]
    if not Solver(clauses, variables=count).solve(budget=budget):
        return None
    choice: dict[str, str] = {}
    fixed: list[Clause] = []
    for name in sorted(packages):
        candidates = sorted(
            (version for version, _ in packages[name] if (name, version) in pick),
            reverse=True,
        )
        for version in candidates:
            assumption = pick[(name, version)]
            probe = Solver([*clauses, *fixed, (assumption,)], variables=count)
            if probe.solve(budget=budget):
                choice[name] = version
                fixed.append((assumption,))
                break
    return choice
