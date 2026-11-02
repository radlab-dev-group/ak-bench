# Complete the type checker of an existing compiler

Implement the missing type system in `src/typeweave`. Read `SPEC.md` first.
The parser, AST, lexical dependency analysis, interpreter, formatter, bytecode
backend and project driver are working. The missing feature spans substitution
and unification, expression inference, recursive binding SCCs, datatype and
annotation elaboration, pattern coverage and independent module interfaces.

This is a soundness task as well as an acceptance task: rejecting valid
polymorphic code is wrong, but accepting a program that breaks mutable-reference
soundness is also wrong. Solve generalization against the normalized surrounding
environment; infer recursive SCCs monomorphically before generalizing completed
components; defer pattern coverage until type constraints are known.

Nested recursive data, constructor aliases, abstract exports, transitive nominal
types and separately loaded interfaces must work together. Diagnostics must
preserve source information and distinguish the documented error classes.
Typed interpreter execution, bytecode execution and module builds must keep
using the existing entry points. Test both successful programs and their nearby
ill-typed variants, including cases that differ only by an expansive binding.

Use the standard library only. Do not change the language, runtime semantics,
primitive signatures, test suite or specifications. The reference solution and
hidden tests remain outside your workspace.
