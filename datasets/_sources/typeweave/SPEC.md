# Type inference implementation contract

## Surface language and execution

The parser uses explicit S-expressions so precedence is never ambiguous.
Integers, JSON strings, true, false and unit are literals. Applications curry:
`(+ 1 2)` is `((+ 1) 2)`. Functions have one parameter: `(fn x BODY)`.
Other expressions are `(let x RHS BODY)`, `(letrec ((x RHS) ...) BODY)`,
`(if CONDITION THEN ELSE)`, `(tuple ...)`, `(ref VALUE)`, `(get REF)`,
`(set REF VALUE)`, `(do EXPR ...)`, `(ann EXPR TYPE)` and
`(match EXPR (PATTERN BODY) ...)`. `(list ...)` desugars to Cons/Nil.

Patterns are literals, `_`, lowercase binding names, `(tuple ...)`, and
constructors such as None or `(Some x)` or `(Cons head tail)`. Nested patterns
are allowed. A variable cannot be bound twice in one pattern. Primitive
signature definitions live in prelude.py and must remain unchanged.

Modules are `(module Name DECLARATION ...)`. Declarations are
`(import Other alias)`, `(def name EXPR)`, `(export NAME ...)` and
`(data TypeName (parameter ...) (Constructor FIELD-TYPE ...) ...)`.
Modules have acyclic imports; value definitions can be mutually recursive.
The existing project driver checks modules in dependency order.

## Types and substitution

Use the existing immutable Variable, Constructor and Scheme records. Primitive
types are Int, Bool, String and Unit. Compound types include `(-> ARG RESULT)`,
`(Tuple ...)`, `(Ref VALUE)`, `(List ELEMENT)`, `(Option ELEMENT)` and declared
nominal data types. Arrows curry. Function application, both if branches,
assignments, annotations and match branches generate equality constraints.
Every variable lookup instantiates just its scheme's quantified variables.

Solver.apply must normalize transitive substitutions. Unification checks
constructor identity and arity and performs a recursive occurs-check before
binding variables. Fresh identities never collide within one checker. Schemes
must never accidentally instantiate a free monomorphic variable. Generalize
the normalized inferred term over variables absent from the NORMALIZED free
variables of the surrounding environment, excluding quantified variables there.

Expression annotation lowercase names are fresh within that one annotation,
shared inside it, and independent between annotations. An annotation is a
unification constraint, not a promise of universal polymorphism. Annotation
type constructors must have the right arity and resolve to known nominal types.

## Let polymorphism, recursive groups and mutation

Only Literal, Variable, Lambda, recursively nonexpansive TupleExpr and
nonexpansive Annotate are nonexpansive. Other RHSs remain monomorphic. This
deliberately conservative value restriction includes constructor applications.
For example, a reference containing an identity function cannot be used at both
Int and Bool after updating it. Lambda parameters and pattern variables are
always monomorphic within their scope.

Use the existing components() function to analyze a binding group by dependency
SCCs. A singleton without a self reference is nonrecursive and can have any
RHS. A genuinely recursive SCC must have only Lambda RHSs. All SCC members
have monomorphic provisional types until every RHS in that SCC has unified;
then generalize relative to the environment OUTSIDE that SCC. Already completed
dependency SCCs are available polymorphically. Do not implement polymorphic
recursion. Lexical shadowing and references to an outer monomorphic variable
must remain correct across generalization.

## Data declarations and pattern coverage

Predeclare every local data arity before elaborating fields. Local data and
constructors have canonical identities Module.Type and Module.Constructor;
equally spelled types from different modules are distinct. Constructor schemes
quantify the declaration's parameters. Only declared parameters may appear in
constructor fields; mutually recursive data declarations are legal. Built-in
Option and List remain structural built-in nominal families from prelude.py.

Infer and unify ALL match cases before checking coverage, including cases whose
RHS constrains an initially unknown subject type. Defer coverage until finish().
Implement usefulness/exhaustiveness with typed pattern matrices or an equivalent
complete algorithm: arbitrary finite constructor nesting, recursive types,
tuples, Bool and Unit must work without a fixed enumeration depth. Int and
String have infinite domains and require a default pattern for exhaustiveness.
A case is redundant precisely when earlier cases already cover every value it
could match. Aliases of the same constructor denote the same matrix head.
Opaque imported types require a wildcard if their entire constructor family
is unavailable. Use source spans on errors, not Python exceptions or booleans.

## Module interfaces

Interface.document() is a detached JSON object with exactly these keys:
`version` (1), `module`, `values`, `data`, `constructors`, `dependencies`.
`values` maps public names to encode_scheme-compatible dictionaries.
`data` maps EXPLICITLY exported local type names to records with `name`
(canonical nominal identity), `parameters` (0..arity-1), and `constructors`
(the complete canonical family, including hidden constructors).
`constructors` contains ONLY explicitly exported constructor values, with
`name`, `owner`, `arity` and `scheme` metadata. The scheme must equal that
constructor's values entry and return its declared owner type.
`dependencies` carries nominal metadata for imported types occurring in public
value schemes, keyed by canonical type name; it does not export their aliases
or constructors. It uses the same metadata shape as data.

Only local definitions, local type names and local constructors can be named
in export declarations. If a type and its constructor share one spelling,
exporting that spelling exports both namespaces. A value mentioning a local type requires exporting
that type, possibly abstractly without its constructors. Imported types may
occur transitively in public value schemes via dependencies. Every public
scheme must be closed: reject unresolved free monomorphic variables. Alpha
normalize each exported scheme independently by first variable occurrence,
assigning quantified identities 0..n-1. Sort object keys when freezing payload.
Changes in private definition order must not change a public interface.

Interface.load validates the shape, version, schemes, type arities, closure,
constructor ownership and arrow arity; malformed input raises ValueError.
It takes an independent snapshot of its input, never retaining caller-owned
dictionaries. import_into freshens each public scheme independently and installs
values/constructors only as alias.name, public data aliases as alias.Type.
Nominal identity remains tied to the originating module. Exported references
with a fully concrete type are legal; weak polymorphic references are not.
Loading interfaces in a fresh interpreter must preserve all these properties.

## Required failures

Raise CompileError with these codes: `type-mismatch`, `infinite-type`,
`unbound-name`, `unknown-type`, `type-arity`, `unknown-constructor`,
`constructor-arity`, `duplicate-binding`, `duplicate-type`,
`duplicate-parameter`, `duplicate-constructor`, `unbound-type-variable`,
`recursive-value`, `redundant-pattern`, `non-exhaustive`, `weak-export`,
`private-type`, `unknown-export`, `duplicate-export`. Existing parser/project
errors remain unchanged. Mismatched constraints with an origin span carry a
Related record pointing at that origin. Every public inferred result is fully
normalized. Reusing typechecking entry points must not leak state across calls.
