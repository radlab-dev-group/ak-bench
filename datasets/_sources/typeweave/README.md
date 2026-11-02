# Typeweave

An offline compiler laboratory for a small strict functional language. The
front end, lexical analysis, SCC dependency analysis, interpreter, formatter,
AST codec, bytecode backend, stack validator, module driver and editor helpers
work. Type checking is a missing feature spanning five modules. Read SPEC.md.

Use Python 3.12 with the standard library. The supplied infrastructure tests
can run before the type checker exists:

```
PYTHONPATH=src python -m pytest tests
PYTHONPATH=src python -m typeweave.cli run example.tw --untyped
```

After implementing the feature, `check`, typed `run`, `vm` and module `build`
must all agree. Work in unification.py, inference.py, coverage.py,
declarations.py and interfaces.py; additional helpers in the package are
allowed. Do not alter the syntax, public records, working runtime semantics,
infrastructure tests, or this contract. There is no hidden reference solution
inside this source project. Diagnostics are structured CompileError objects.

The package also includes source package snapshots and dependency impact analysis
(`package.py`, `dependency_graph.py`), atomic checksummed build artifacts
(`artifacts.py`), interface-sensitive incremental compilation (`compiler.py`),
VM module linking (`linker.py`), bytecode inspection (`inspection.py`), lexical
alpha conversion and effect/call analysis, UTF-16 editor buffers and versioned
diagnostic publication. The typed paths of these tools depend on the missing
feature. Preserve their APIs and integrate through the existing checker entry
points instead of creating a parallel type system.
