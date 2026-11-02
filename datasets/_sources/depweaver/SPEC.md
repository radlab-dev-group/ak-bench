# Resolution and repair contract

## Metadata

Names and extras normalize runs of dash/underscore/dot to a lowercase dash.
Release identities are normalized name plus semantic version (build metadata
does not change ordering/equality). SemVer prerelease numeric segments compare
numerically. Specs are ORs (`||`) of comma-conjoined comparisons: ==, !=, <,
<=, >, >=, caret, tilde and trailing wildcard equality. Version ranges concern
precedence; prerelease eligibility is a separate policy decision.

Dependency(name, spec='*', extras=(), marker='') specifies a target package,
required range and optional features to ACTIVATE ON THAT TARGET package.
Release declares available extras, dependencies, requires_python, yanked state
and an optional artifact digest. Repository metadata is immutable during one
solve. Fingerprints include complete metadata and are order-independent at
repository/release insertion level. Dependency declaration ordering must never
change the selected result.

## Activation and markers

Start from root requirements whose markers hold. Track the UNION of every
active requirement's requested extras per target package. Re-expand a selected
release whenever its active extra set grows, even if it was already expanded
at an earlier fixed-point iteration. Keep cyclic propagation finite by tracking
all relevant expansion context. Only reachable active dependencies participate.

A dependency marker evaluates in request.target and the extras of the package
DECLARING that dependency, not the target dependency's extras. With no extra,
evaluate once with extra=''; otherwise evaluate once per active extra and OR
the answers. Supported fields: python_version, sys_platform, platform_machine,
implementation_name and extra. `and` binds tighter than `or`; parentheses work.
Strings are quoted. Python versions compare numerically; other fields compare
lexically. `in` and `not in` compare against comma-separated exact strings.
Markers must be parsed, never passed to eval/exec.

## Domains, preferences and locks

A candidate must satisfy ALL active ranges, support ALL requested extras, and
support target Python. Yanked releases are excluded unless policy allows them
or that exact version is already locked. Prereleases are excluded unless policy
allows them, an active range explicitly mentions a prerelease, or that exact
version is already locked. Locked packages outside request.update are hard
pins WHEN REACHABLE. Pins do not activate otherwise unreachable packages.
Only explicitly updated package names may move; updating one package does not
implicitly unlock every other pin. Unsupported pins make the request unsatisfiable.

Choose an unresolved package with the smallest eligible domain, ties by
normalized package name. Try semantic versions from highest to lowest, or
lowest to highest with prefer_lowest. Return the first complete valid result
under that decision ordering. Safe pruning must preserve that result. A solution
contains exactly the reachable closure, in package-name order, with the final
union of extras. SearchLimit is distinct from Unsatisfiable.

## Search invariants

Each trail level holds one exact package/version decision. rollback(saved)
discards EVERY decision above saved from both the decision list and selected
map. No dependency, extra, expansion key or constraint introduced by a discarded
branch may constrain a sibling branch. Recomputing closure is allowed.

Conflict explanations contain exact decisions sufficient to imply the conflict,
including all parent requirement/feature provenance needed for that implication.
An incompatibility clause forbids the conjunction of its members, not every
member separately. Never drop contextual decisions when learning. A conflict
independent of the current decision can return past that decision; otherwise
try the next candidate before declaring its parent impossible. A solver may use
a more conservative valid explanation, but must remain complete and preserve
the preference rule. Learned incompatibilities are scoped to ONE solve request.

Cache keys must distinguish repository metadata, package, active ranges, union
of extras, target environment, policy, pins and update set. A cache hit cannot
change satisfiability or the preferred result. Reusing one Resolver across
different roots, extras, targets or partial updates must agree with fresh solvers.
Do not disable caches/learning/backjumping as the repair: keep each mechanism
operational and sound. Repository tests and the integrity suite inspect these
mechanisms and compare complete solve behavior.

## Errors and integrity

Missing metadata/versions, impossible ranges, unsupported extras and conflicts
raise Unsatisfiable with a structured Conflict, not KeyError, recursion errors
or fabricated partial results. A failed solve leaves the repository unchanged
and cannot poison a later solve. Invalid input metadata raises ValueError.
Lockfile publication remains checksummed and target-bound. Validation must keep
checking dependency closure, feature closure, all pins and metadata integrity.

The task contains eight related regressions. Hidden tests have a separate
counterexample for each and mixed generated traces. Small repository results
are compared with an independent exhaustive oracle. Larger families require
constraint-directed search; do not special-case their package names.
