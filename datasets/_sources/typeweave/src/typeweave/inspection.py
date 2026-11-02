"""Bytecode introspection, nested instruction metrics and lexical load analysis."""

from dataclasses import dataclass

from .bytecode import Code, Instruction, validate
from .source import Span


@dataclass(frozen=True)
class Location:
    path: tuple[int, ...]
    instruction: Instruction

    def document(self) -> dict:
        return {
            "path": list(self.path),
            "operation": self.instruction.operation,
            "span": self.instruction.span.document(),
        }


def nested(instruction: Instruction) -> tuple[Code, ...]:
    operation, operand = instruction.operation, instruction.operand
    if operation == "closure":
        return (operand[1],)
    if operation == "branch":
        return operand
    if operation in {"recursive", "match"}:
        return tuple(body for binding, body in operand)
    return ()


def locations(code: Code, prefix: tuple[int, ...] = ()) -> tuple[Location, ...]:
    result = []
    for index, instruction in enumerate(code.instructions):
        path = (*prefix, index)
        result.append(Location(path, instruction))
        for child_index, child in enumerate(nested(instruction)):
            result.extend(locations(child, (*path, child_index)))
    return tuple(result)


def free_loads(code: Code, initial: frozenset[str] = frozenset()) -> tuple[str, ...]:
    from .ast import pattern_names

    def visit(current, names):
        stack, free = [set(names)], set()
        for instruction in current.instructions:
            operation, operand = instruction.operation, instruction.operand
            if operation == "load":
                if operand not in stack[-1]:
                    free.add(operand)
            elif operation == "enter":
                stack.append(stack[-1] | {operand})
            elif operation == "leave":
                if len(stack) == 1:
                    raise ValueError("unbalanced lexical bytecode scopes")
                stack.pop()
            elif operation == "recursive":
                stack.append(stack[-1] | {name for name, body in operand})
                for _name, body in operand:
                    free.update(visit(body, stack[-1]))
            elif operation == "closure":
                free.update(visit(operand[1], stack[-1] | {operand[0]}))
            elif operation == "match":
                for pattern, body in operand:
                    free.update(visit(body, stack[-1] | set(pattern_names(pattern))))
            elif operation == "branch":
                for branch in operand:
                    free.update(visit(branch, stack[-1]))
        if len(stack) != 1:
            raise ValueError("unbalanced lexical bytecode scopes")
        return free

    validate(code)
    return tuple(sorted(visit(code, initial)))


def metrics(code: Code) -> dict:
    rows = locations(code)
    counts = {}
    for row in rows:
        operation = row.instruction.operation
        counts[operation] = counts.get(operation, 0) + 1
    return {
        "instructions": len(rows),
        "maximum_stack": validate(code),
        "maximum_nesting": max((len(row.path) // 2 for row in rows), default=0),
        "free_loads": list(free_loads(code)),
        "operations": dict(sorted(counts.items())),
    }


def disassemble(code: Code) -> str:
    lines = []
    for row in locations(code):
        instruction = row.instruction
        operand = instruction.operand
        if instruction.operation == "closure":
            rendered = operand[0]
        elif instruction.operation in {"branch", "match", "recursive"}:
            rendered = f"<{len(nested(instruction))} blocks>"
        else:
            rendered = repr(operand)
        address = ".".join(str(index) for index in row.path)
        source = f"{instruction.span.source}:{instruction.span.start.line}"
        lines.append(f"{address:>12}  {instruction.operation:<12} {rendered}  ; {source}")
    return "\n".join(lines) + "\n"


def instructions_at(code: Code, span: Span) -> tuple[Location, ...]:
    return tuple(
        row
        for row in locations(code)
        if row.instruction.span.source == span.source
        and row.instruction.span.start.offset < span.end.offset
        and span.start.offset < row.instruction.span.end.offset
    )
