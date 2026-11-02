"""Compiler tooling: typecheck, run, format, AST, bytecode and project builds."""

import argparse
import json
from pathlib import Path

from . import bytecode, pretty, syntax_codec
from .diagnostics import CompileError, EvaluationError
from .interpreter import Interpreter, to_document
from .parser import parse, parse_module
from .project import build, check_expression, execute
from .types import render
from .workspace import discover


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="typeweave")
    parser.add_argument(
        "command", choices=("check", "run", "format", "ast", "compile", "vm", "build")
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--module")
    parser.add_argument("--binding", default="main")
    parser.add_argument("--fuel", type=int, default=100_000)
    parser.add_argument("--untyped", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "build":
            result = build(discover(arguments.path))
            if arguments.module:
                output = to_document(
                    execute(result, arguments.module, arguments.binding, fuel=arguments.fuel)
                )
            else:
                output = {name: result.modules[name].interface.document() for name in result.order}
            print(json.dumps(output, sort_keys=True))
            return 0
        text = arguments.path.read_text(encoding="utf-8")
        if arguments.command == "format":
            if text.lstrip().startswith("(module "):
                print(pretty.module(parse_module(text, str(arguments.path))), end="")
            else:
                print(pretty.expression(parse(text, str(arguments.path))))
            return 0
        syntax = parse(text, str(arguments.path))
        if arguments.command == "ast":
            print(json.dumps(syntax_codec.encode(syntax), sort_keys=True))
            return 0
        if not arguments.untyped:
            inferred = check_expression(text, name=str(arguments.path))
            if arguments.command == "check":
                print(render(inferred))
                return 0
        if arguments.command == "compile":
            print(json.dumps(bytecode.compile(syntax).document(), sort_keys=True))
        elif arguments.command == "vm":
            print(
                json.dumps(
                    to_document(bytecode.Machine(fuel=arguments.fuel).run(bytecode.compile(syntax)))
                )
            )
        elif arguments.command == "run":
            print(json.dumps(to_document(Interpreter(fuel=arguments.fuel).evaluate(syntax))))
        return 0
    except CompileError as error:
        print(json.dumps({"error": error.diagnostic.document()}, sort_keys=True))
        return 1
    except (EvaluationError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
