"""Portable structured bytecode and a stack machine independent of inference."""

import hashlib
import json
from dataclasses import dataclass

from . import ast
from .diagnostics import EvaluationError
from .interpreter import UNINITIALIZED, Cell, Primitive, Scope, builtins, match_pattern
from .source import Span
from .syntax_codec import decode, decode_span, encode


@dataclass(frozen=True)
class Instruction:
    operation: str
    operand: object
    span: Span


@dataclass(frozen=True)
class Code:
    instructions: tuple[Instruction, ...]

    def document(self) -> dict:
        rows = []
        for instruction in self.instructions:
            operand = instruction.operand
            if instruction.operation == "closure":
                operand = {"parameter": operand[0], "body": operand[1].document()}
            elif instruction.operation == "branch":
                operand = [code.document() for code in operand]
            elif instruction.operation == "recursive":
                operand = [[name, code.document()] for name, code in operand]
            elif instruction.operation == "match":
                operand = [[encode(pattern), code.document()] for pattern, code in operand]
            rows.append(
                {
                    "operation": instruction.operation,
                    "operand": operand,
                    "span": instruction.span.document(),
                }
            )
        return {"version": 1, "instructions": rows}

    @classmethod
    def load(cls, document: dict, *, depth: int = 0) -> "Code":
        if depth > 500 or not isinstance(document, dict) or document.get("version") != 1:
            raise ValueError("invalid bytecode document")
        if not isinstance(document.get("instructions"), list):
            raise ValueError("bytecode instructions must be a list")
        instructions = []
        for row in document["instructions"]:
            operation, operand = row["operation"], row["operand"]
            span = decode_span(row["span"])
            if operation == "closure":
                operand = (operand["parameter"], cls.load(operand["body"], depth=depth + 1))
            elif operation == "branch":
                if len(operand) != 2:
                    raise ValueError("invalid branch")
                operand = tuple(cls.load(item, depth=depth + 1) for item in operand)
            elif operation == "recursive":
                operand = tuple((name, cls.load(code, depth=depth + 1)) for name, code in operand)
            elif operation == "match":
                operand = tuple(
                    (decode(pattern), cls.load(code, depth=depth + 1)) for pattern, code in operand
                )
                if any(not isinstance(pattern, ast.Pattern) for pattern, code in operand):
                    raise ValueError("invalid match pattern")
            elif operation not in {
                "constant",
                "load",
                "call",
                "enter",
                "leave",
                "tuple",
                "ref",
                "get",
                "set",
                "drop",
            }:
                raise ValueError("unknown bytecode instruction")
            instructions.append(Instruction(operation, operand, span))
        code = cls(tuple(instructions))
        validate(code)
        return code

    @property
    def fingerprint(self) -> str:
        data = json.dumps(self.document(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(data).hexdigest()


def compile(expression: ast.Expression) -> Code:
    instructions = []

    def emit(operation: str, operand=None, span: Span | None = None) -> None:
        instructions.append(Instruction(operation, operand, span or expression.span))

    def lower(node: ast.Expression) -> None:
        if isinstance(node, ast.Literal):
            emit("constant", node.value, node.span)
        elif isinstance(node, ast.Variable):
            emit("load", node.name, node.span)
        elif isinstance(node, ast.Lambda):
            emit("closure", (node.parameter, compile(node.body)), node.span)
        elif isinstance(node, ast.Apply):
            lower(node.function)
            lower(node.argument)
            emit("call", span=node.span)
        elif isinstance(node, ast.Let):
            lower(node.value)
            emit("enter", node.name, node.span)
            lower(node.body)
            emit("leave", span=node.span)
        elif isinstance(node, ast.LetRec):
            from .names import components

            groups = tuple(binding for group in components(node.bindings) for binding in group)
            emit(
                "recursive",
                tuple((binding.name, compile(binding.value)) for binding in groups),
                node.span,
            )
            lower(node.body)
            emit("leave", span=node.span)
        elif isinstance(node, ast.If):
            lower(node.condition)
            emit("branch", (compile(node.consequent), compile(node.alternative)), node.span)
        elif isinstance(node, ast.TupleExpr):
            for item in node.items:
                lower(item)
            emit("tuple", len(node.items), node.span)
        elif isinstance(node, ast.Ref):
            lower(node.value)
            emit("ref", span=node.span)
        elif isinstance(node, ast.Deref):
            lower(node.reference)
            emit("get", span=node.span)
        elif isinstance(node, ast.Assign):
            lower(node.reference)
            lower(node.value)
            emit("set", span=node.span)
        elif isinstance(node, ast.Sequence):
            for index, item in enumerate(node.items):
                lower(item)
                if index < len(node.items) - 1:
                    emit("drop", span=item.span)
        elif isinstance(node, ast.Annotate):
            lower(node.value)
        elif isinstance(node, ast.Match):
            lower(node.value)
            emit(
                "match", tuple((case.pattern, compile(case.body)) for case in node.cases), node.span
            )
        else:
            raise TypeError(type(node).__name__)

    lower(expression)
    return Code(tuple(instructions))


def validate(code: Code) -> int:
    height = maximum = scopes = 0
    for instruction in code.instructions:
        operation, operand = instruction.operation, instruction.operand
        needed, delta = {
            "constant": (0, 1),
            "load": (0, 1),
            "closure": (0, 1),
            "call": (2, -1),
            "enter": (1, -1),
            "leave": (0, 0),
            "ref": (1, 0),
            "get": (1, 0),
            "set": (2, -1),
            "drop": (1, -1),
            "branch": (1, 0),
            "match": (1, 0),
            "recursive": (0, 0),
            "tuple": (0, 0),
        }.get(operation, (-1, 0))
        if needed < 0:
            raise ValueError("unknown instruction")
        if operation == "tuple":
            if type(operand) is not int or operand < 0:
                raise ValueError("invalid tuple instruction")
            needed, delta = operand, 1 - operand
        if height < needed:
            raise ValueError("bytecode stack underflow")
        height += delta
        maximum = max(maximum, height)
        if operation in {"enter", "recursive"}:
            scopes += 1
        elif operation == "leave":
            scopes -= 1
            if scopes < 0:
                raise ValueError("bytecode scope underflow")
        if operation == "closure":
            validate(operand[1])
        elif operation == "branch":
            for branch in operand:
                validate(branch)
        elif operation in {"match", "recursive"}:
            for _name, body in operand:
                validate(body)
    if height != 1 or scopes:
        raise ValueError("bytecode does not return one balanced result")
    return maximum


@dataclass
class CompiledClosure:
    parameter: str
    code: Code
    scope: Scope
    constructors: dict[str, str]


class Machine:
    def __init__(self, *, fuel: int = 100_000, constructors: dict[str, str] | None = None) -> None:
        self.fuel = fuel
        self.constructors = constructors or {}

    def run(self, code: Code, scope: Scope | None = None) -> object:
        validate(code)
        scope = builtins() if scope is None else scope
        stack = []
        for instruction in code.instructions:
            self.fuel -= 1
            if self.fuel < 0:
                raise EvaluationError("bytecode fuel exhausted", instruction.span)
            operation, operand = instruction.operation, instruction.operand
            if operation == "constant":
                stack.append(operand)
            elif operation == "load":
                stack.append(scope.get(operand, instruction.span))
            elif operation == "closure":
                stack.append(
                    CompiledClosure(operand[0], operand[1], scope, self.constructors.copy())
                )
            elif operation == "call":
                argument, function = stack.pop(), stack.pop()
                if isinstance(function, CompiledClosure):
                    previous = self.constructors
                    self.constructors = function.constructors
                    try:
                        value = self.run(
                            function.code, function.scope.child({function.parameter: argument})
                        )
                    finally:
                        self.constructors = previous
                elif isinstance(function, Primitive):
                    try:
                        value = function.apply(argument)
                    except (ValueError, TypeError, ZeroDivisionError) as error:
                        raise EvaluationError(str(error), instruction.span) from error
                else:
                    raise EvaluationError("call requires a function", instruction.span)
                stack.append(value)
            elif operation == "enter":
                scope = scope.child({operand: stack.pop()})
            elif operation == "leave":
                scope = scope.parent
            elif operation == "tuple":
                values = tuple(stack[-operand:]) if operand else ()
                if operand:
                    del stack[-operand:]
                stack.append(values)
            elif operation == "branch":
                condition = stack.pop()
                if type(condition) is not bool:
                    raise EvaluationError("branch requires Bool", instruction.span)
                stack.append(self.run(operand[0] if condition else operand[1], scope))
            elif operation == "recursive":
                scope = scope.child(dict.fromkeys((name for name, body in operand), UNINITIALIZED))
                for name, body in operand:
                    scope.values[name] = self.run(body, scope)
            elif operation == "ref":
                stack.append(Cell(stack.pop()))
            elif operation in {"get", "set"}:
                value = stack.pop() if operation == "set" else None
                cell = stack.pop()
                if not isinstance(cell, Cell):
                    raise EvaluationError("reference operation requires Ref", instruction.span)
                if operation == "set":
                    cell.value = value
                    stack.append(None)
                else:
                    stack.append(cell.value)
            elif operation == "drop":
                stack.pop()
            elif operation == "match":
                subject = stack.pop()
                for pattern, body in operand:
                    bindings = match_pattern(pattern, subject, self.constructors)
                    if bindings is not None:
                        stack.append(self.run(body, scope.child(bindings)))
                        break
                else:
                    raise EvaluationError("unmatched value", instruction.span)
        return stack[0]
