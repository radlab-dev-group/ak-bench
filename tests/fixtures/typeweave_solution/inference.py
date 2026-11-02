"""Reference Algorithm W, deferred coverage and SCC inference."""

from dataclasses import dataclass

from . import ast, coverage
from .declarations import annotation
from .diagnostics import CompileError
from .environment import Environment, nonexpansive
from .names import components, free_names
from .types import BOOL, INT, STRING, UNIT, Constructor, Scheme, Type, arrow
from .unification import Solver


@dataclass(frozen=True)
class Inference:
    type: Type
    bindings: dict[str, Scheme]


class Inferencer:
    def __init__(self, solver: Solver | None = None) -> None:
        self.solver = solver or Solver()
        self.coverage_obligations: list = []

    def expression(self, expression: ast.Expression, environment: Environment) -> Type:
        solver = self.solver
        if isinstance(expression, ast.Literal):
            return {bool: BOOL, int: INT, str: STRING, type(None): UNIT}[type(expression.value)]
        if isinstance(expression, ast.Variable):
            return solver.instantiate(environment.lookup(expression.name, expression.span))
        if isinstance(expression, ast.Lambda):
            argument = solver.fresh()
            child = environment.extend({expression.parameter: Scheme((), argument)})
            result = self.expression(expression.body, child)
            return arrow(solver.apply(argument), solver.apply(result))
        if isinstance(expression, ast.Apply):
            function = self.expression(expression.function, environment)
            argument = self.expression(expression.argument, environment)
            result = solver.fresh()
            solver.unify(
                function, arrow(argument, result), expression.span, expression.function.span
            )
            return solver.apply(result)
        if isinstance(expression, ast.Let):
            value = self.expression(expression.value, environment)
            scheme = solver.generalize(value, environment, allow=nonexpansive(expression.value))
            return self.expression(expression.body, environment.extend({expression.name: scheme}))
        if isinstance(expression, ast.LetRec):
            return self.expression(expression.body, self.group(expression.bindings, environment))
        if isinstance(expression, ast.If):
            condition = self.expression(expression.condition, environment)
            solver.unify(condition, BOOL, expression.condition.span)
            first = self.expression(expression.consequent, environment)
            second = self.expression(expression.alternative, environment)
            solver.unify(first, second, expression.alternative.span, expression.consequent.span)
            return solver.apply(first)
        if isinstance(expression, ast.TupleExpr):
            return Constructor(
                "Tuple", tuple(self.expression(item, environment) for item in expression.items)
            )
        if isinstance(expression, ast.Ref):
            return Constructor("Ref", (self.expression(expression.value, environment),))
        if isinstance(expression, ast.Deref):
            value = solver.fresh()
            reference = self.expression(expression.reference, environment)
            solver.unify(reference, Constructor("Ref", (value,)), expression.span)
            return solver.apply(value)
        if isinstance(expression, ast.Assign):
            reference = self.expression(expression.reference, environment)
            value = self.expression(expression.value, environment)
            solver.unify(reference, Constructor("Ref", (value,)), expression.span)
            return UNIT
        if isinstance(expression, ast.Sequence):
            result = UNIT
            for item in expression.items:
                result = self.expression(item, environment)
            return result
        if isinstance(expression, ast.Annotate):
            inferred = self.expression(expression.value, environment)
            declared = annotation(expression.annotation, environment, solver)
            solver.unify(inferred, declared, expression.annotation.span, expression.value.span)
            return solver.apply(inferred)
        if isinstance(expression, ast.Match):
            subject = self.expression(expression.value, environment)
            result = solver.fresh()
            for case in expression.cases:
                bindings = self.pattern(case.pattern, subject, environment)
                branch = self.expression(case.body, environment.extend(bindings))
                solver.unify(result, branch, case.body.span, expression.span)
            self.coverage_obligations.append((expression, subject, environment))
            return solver.apply(result)
        raise TypeError(type(expression).__name__)

    def group(self, bindings: tuple[ast.Binding, ...], environment: Environment) -> Environment:
        result = environment
        for group in components(bindings):
            recursive = len(group) > 1 or group[0].name in free_names(group[0].value)
            if recursive and any(not isinstance(binding.value, ast.Lambda) for binding in group):
                raise CompileError(
                    "recursive-value", "recursive definitions must be functions", group[0].span
                )
            variables = {binding.name: self.solver.fresh() for binding in group}
            inner = result.extend({name: Scheme((), term) for name, term in variables.items()})
            for binding in group:
                term = self.expression(binding.value, inner)
                self.solver.unify(variables[binding.name], term, binding.span)
            schemes = {
                binding.name: self.solver.generalize(
                    variables[binding.name], result, allow=nonexpansive(binding.value)
                )
                for binding in group
            }
            result = result.extend(schemes)
        return result

    def pattern(
        self, pattern: ast.Pattern, expected: Type, environment: Environment
    ) -> dict[str, Scheme]:
        solver = self.solver
        if pattern.kind == "wildcard":
            return {}
        if pattern.kind == "variable":
            return {pattern.name: Scheme((), expected)}
        if pattern.kind == "literal":
            term = {bool: BOOL, int: INT, str: STRING, type(None): UNIT}[type(pattern.value)]
            solver.unify(expected, term, pattern.span)
            return {}
        if pattern.kind == "tuple":
            arguments = tuple(solver.fresh() for item in pattern.arguments)
            solver.unify(expected, Constructor("Tuple", arguments), pattern.span)
        else:
            info = environment.constructor(pattern.name, pattern.span)
            if len(pattern.arguments) != info.arity:
                raise CompileError(
                    "constructor-arity", "pattern constructor arity mismatch", pattern.span
                )
            term = solver.instantiate(info.scheme)
            arguments = []
            for _index in range(info.arity):
                arguments.append(term.arguments[0])
                term = term.arguments[1]
            solver.unify(expected, term, pattern.span)
        bindings = {}
        for child, term in zip(pattern.arguments, arguments, strict=True):
            found = self.pattern(child, term, environment)
            if bindings.keys() & found.keys():
                raise CompileError("duplicate-binding", "duplicate pattern variable", child.span)
            bindings.update(found)
        return bindings

    def finish(self) -> None:
        obligations, self.coverage_obligations = self.coverage_obligations, []
        for match, subject, environment in obligations:
            coverage.check(match, self.solver.apply(subject), environment, self.solver)
