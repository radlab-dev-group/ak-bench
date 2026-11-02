"""Reference typed pattern-matrix specialization without depth enumeration."""

from . import ast
from .diagnostics import CompileError
from .environment import Environment
from .source import Span
from .types import Constructor, Type


def check(match: ast.Match, subject: Type, environment: Environment, solver) -> None:
    wildcard = ast.Pattern(Span.synthetic(), "wildcard")

    def wild(pattern):
        return pattern.kind in {"wildcard", "variable"}

    def head(pattern):
        if pattern.kind == "literal":
            return "literal", type(pattern.value).__name__, pattern.value
        if pattern.kind == "tuple":
            return "tuple", len(pattern.arguments)
        return "constructor", environment.constructor(pattern.name, pattern.span).name

    def signature(term):
        term = solver.apply(term)
        if not isinstance(term, Constructor):
            return None
        if term.name == "Bool":
            return [(("literal", "bool", False), ()), (("literal", "bool", True), ())]
        if term.name == "Unit":
            return [(("literal", "NoneType", None), ())]
        if term.name == "Tuple":
            return [(("tuple", len(term.arguments)), term.arguments)]
        infos = [info for info in environment.data.values() if info.name == term.name]
        if not infos:
            return None
        constructors = {
            info.name: info for info in environment.constructors.values() if info.owner == term.name
        }
        info = infos[0]
        if set(constructors) != set(info.constructors):
            return None
        result = []
        for name in info.constructors:
            constructor = constructors[name]
            instance = solver.instantiate(constructor.scheme)
            fields = []
            for _index in range(constructor.arity):
                fields.append(instance.arguments[0])
                instance = instance.arguments[1]
            solver.unify(instance, term, match.span)
            result.append((("constructor", name), tuple(solver.apply(field) for field in fields)))
        return result

    def fields(pattern, term):
        if pattern.kind == "tuple":
            return solver.apply(term).arguments
        if pattern.kind == "literal":
            return ()
        info = environment.constructor(pattern.name, pattern.span)
        instance = solver.instantiate(info.scheme)
        result = []
        for _index in range(info.arity):
            result.append(instance.arguments[0])
            instance = instance.arguments[1]
        solver.unify(instance, term, pattern.span)
        return tuple(solver.apply(field) for field in result)

    def specialize(matrix, tag, count):
        result = []
        for row in matrix:
            if wild(row[0]):
                result.append((wildcard,) * count + row[1:])
            elif head(row[0]) == tag:
                result.append(row[0].arguments + row[1:])
        return result

    def useful(matrix, vector, types):
        if not vector:
            return not matrix
        pattern, tail = vector[0], vector[1:]
        if not wild(pattern):
            arguments = fields(pattern, types[0])
            return useful(
                specialize(matrix, head(pattern), len(arguments)),
                pattern.arguments + tail,
                arguments + types[1:],
            )
        finite = signature(types[0])
        present = {head(row[0]) for row in matrix if not wild(row[0])}
        if finite is not None and all(tag in present for tag, arguments in finite):
            return any(
                useful(
                    specialize(matrix, tag, len(arguments)),
                    (wildcard,) * len(arguments) + tail,
                    arguments + types[1:],
                )
                for tag, arguments in finite
            )
        defaults = [row[1:] for row in matrix if wild(row[0])]
        return useful(defaults, tail, types[1:])

    matrix = []
    for case in match.cases:
        if not useful(matrix, (case.pattern,), (subject,)):
            raise CompileError("redundant-pattern", "case is already covered", case.pattern.span)
        matrix.append((case.pattern,))
    if useful(matrix, (wildcard,), (subject,)):
        raise CompileError("non-exhaustive", "match does not cover all values", match.span)
