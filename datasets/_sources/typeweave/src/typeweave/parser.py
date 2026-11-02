"""Surface parser with explicit arity checks and precise error spans."""

from dataclasses import dataclass

from . import ast
from .diagnostics import CompileError
from .lexer import Token, lex
from .source import Source, Span


@dataclass(frozen=True)
class Form:
    span: Span
    atom: Token | None = None
    items: tuple["Form", ...] = ()

    def symbol(self) -> str:
        if self.atom is None or self.atom.kind != "symbol":
            raise CompileError("syntax", "expected a name", self.span)
        return str(self.atom.value)


def forms(text: str, name: str = "<input>") -> tuple[Form, ...]:
    tokens = lex(Source(text, name))
    cursor = 0

    def read() -> Form:
        nonlocal cursor
        token = tokens[cursor]
        cursor += 1
        if token.kind == "(":
            items = []
            while tokens[cursor].kind != ")":
                if tokens[cursor].kind == "eof":
                    raise CompileError("syntax", "unclosed form", token.span)
                items.append(read())
            closing = tokens[cursor]
            cursor += 1
            return Form(token.span.union(closing.span), items=tuple(items))
        if token.kind in {"eof", ")"}:
            raise CompileError("syntax", "unexpected closing delimiter", token.span)
        return Form(token.span, atom=token)

    result = []
    while tokens[cursor].kind != "eof":
        result.append(read())
    return tuple(result)


def arity(form: Form, count: int) -> None:
    if form.atom is not None or len(form.items) != count:
        raise CompileError("syntax", f"expected {count - 1} operands", form.span)


def identifier(form: Form, *, constructor: bool = False) -> str:
    name = form.symbol()
    if "." in name or name in {"true", "false", "unit", "_"}:
        raise CompileError("syntax", "invalid binding name", form.span)
    if constructor and not name[0].isupper():
        raise CompileError("syntax", "constructor/type name must start uppercase", form.span)
    return name


def type_syntax(form: Form) -> ast.TypeSyntax:
    if form.atom is not None:
        return ast.TypeSyntax(form.span, form.symbol())
    if not form.items:
        raise CompileError("syntax", "empty type application", form.span)
    return ast.TypeSyntax(
        form.span, form.items[0].symbol(), tuple(type_syntax(item) for item in form.items[1:])
    )


def pattern(form: Form) -> ast.Pattern:
    if form.atom is not None:
        token = form.atom
        if token.kind in {"integer", "string"}:
            return ast.Pattern(form.span, "literal", value=token.value)
        if token.value in {"true", "false", "unit"}:
            values = {"true": True, "false": False, "unit": None}
            return ast.Pattern(form.span, "literal", value=values[token.value])
        if token.value == "_":
            return ast.Pattern(form.span, "wildcard")
        name = form.symbol()
        if name.split(".")[-1][0].isupper():
            return ast.Pattern(form.span, "constructor", name)
        return ast.Pattern(form.span, "variable", identifier(form))
    if not form.items:
        raise CompileError("syntax", "empty pattern", form.span)
    name = form.items[0].symbol()
    kind = "tuple" if name == "tuple" else "constructor"
    result = ast.Pattern(
        form.span, kind, name, arguments=tuple(pattern(item) for item in form.items[1:])
    )
    names = ast.pattern_names(result)
    if len(set(names)) != len(names):
        raise CompileError("duplicate-binding", "pattern binds a name more than once", form.span)
    return result


def expression(form: Form) -> ast.Expression:
    if form.atom is not None:
        token = form.atom
        if token.kind in {"integer", "string"}:
            return ast.Literal(form.span, token.value)
        if token.value in {"true", "false", "unit"}:
            return ast.Literal(form.span, {"true": True, "false": False, "unit": None}[token.value])
        return ast.Variable(form.span, form.symbol())
    if not form.items:
        raise CompileError("syntax", "empty expression", form.span)
    head = (
        form.items[0].symbol() if form.items[0].atom and form.items[0].atom.kind == "symbol" else ""
    )
    if head == "fn":
        arity(form, 3)
        return ast.Lambda(form.span, identifier(form.items[1]), expression(form.items[2]))
    if head == "let":
        arity(form, 4)
        return ast.Let(
            form.span,
            identifier(form.items[1]),
            expression(form.items[2]),
            expression(form.items[3]),
        )
    if head == "letrec":
        arity(form, 3)
        bindings = bindings_form(form.items[1])
        return ast.LetRec(form.span, bindings, expression(form.items[2]))
    if head == "if":
        arity(form, 4)
        return ast.If(form.span, *(expression(item) for item in form.items[1:]))
    if head in {"tuple", "do"}:
        items = tuple(expression(item) for item in form.items[1:])
        if head == "do" and not items:
            raise CompileError("syntax", "do requires an expression", form.span)
        return (
            ast.TupleExpr(form.span, items) if head == "tuple" else ast.Sequence(form.span, items)
        )
    if head in {"ref", "get"}:
        arity(form, 2)
        value = expression(form.items[1])
        return ast.Ref(form.span, value) if head == "ref" else ast.Deref(form.span, value)
    if head == "set":
        arity(form, 3)
        return ast.Assign(form.span, expression(form.items[1]), expression(form.items[2]))
    if head == "ann":
        arity(form, 3)
        return ast.Annotate(form.span, expression(form.items[1]), type_syntax(form.items[2]))
    if head == "match":
        if len(form.items) < 3:
            raise CompileError("syntax", "match requires cases", form.span)
        cases = []
        for item in form.items[2:]:
            arity(item, 2)
            cases.append(ast.Case(item.span, pattern(item.items[0]), expression(item.items[1])))
        return ast.Match(form.span, expression(form.items[1]), tuple(cases))
    if head == "list":
        result = ast.Variable(form.span, "Nil")
        for item in reversed(form.items[1:]):
            constructor = ast.Apply(form.span, ast.Variable(form.span, "Cons"), expression(item))
            result = ast.Apply(form.span, constructor, result)
        return result
    result = expression(form.items[0])
    if len(form.items) == 1:
        return result
    for item in form.items[1:]:
        result = ast.Apply(form.span, result, expression(item))
    return result


def bindings_form(form: Form) -> tuple[ast.Binding, ...]:
    if form.atom is not None or not form.items:
        raise CompileError("syntax", "expected nonempty binding group", form.span)
    result = []
    for item in form.items:
        arity(item, 2)
        result.append(ast.Binding(item.span, identifier(item.items[0]), expression(item.items[1])))
    names = [item.name for item in result]
    if len(names) != len(set(names)):
        raise CompileError("duplicate-binding", "duplicate definition", form.span)
    return tuple(result)


def parse(text: str, name: str = "<input>") -> ast.Expression:
    parsed = forms(text, name)
    if len(parsed) != 1:
        span = parsed[0].span if parsed else Span.synthetic(name)
        raise CompileError("syntax", "expected exactly one expression", span)
    return expression(parsed[0])


def parse_module(text: str, name: str = "<module>") -> ast.Module:
    parsed = forms(text, name)
    if len(parsed) != 1 or parsed[0].atom is not None or len(parsed[0].items) < 2:
        raise CompileError("syntax", "expected a module form", Span.synthetic(name))
    form = parsed[0]
    if form.items[0].symbol() != "module":
        raise CompileError("syntax", "expected module", form.span)
    module_name = identifier(form.items[1], constructor=True)
    imports, data, definitions, exports = [], [], [], []
    for declaration in form.items[2:]:
        if declaration.atom is not None or not declaration.items:
            raise CompileError("syntax", "invalid declaration", declaration.span)
        kind = declaration.items[0].symbol()
        if kind == "import":
            arity(declaration, 3)
            imports.append(
                ast.Import(
                    declaration.span,
                    identifier(declaration.items[1], constructor=True),
                    identifier(declaration.items[2]),
                )
            )
        elif kind == "def":
            arity(declaration, 3)
            definitions.append(
                ast.Binding(
                    declaration.span,
                    identifier(declaration.items[1]),
                    expression(declaration.items[2]),
                )
            )
        elif kind == "export":
            exports.extend(item.symbol() for item in declaration.items[1:])
        elif kind == "data":
            if len(declaration.items) < 4:
                raise CompileError(
                    "syntax", "data requires parameters and constructors", declaration.span
                )
            type_name = identifier(declaration.items[1], constructor=True)
            parameters_form = declaration.items[2]
            if parameters_form.atom is not None:
                raise CompileError("syntax", "parameters must be a form", parameters_form.span)
            parameters = tuple(identifier(item) for item in parameters_form.items)
            constructors = []
            for constructor in declaration.items[3:]:
                if constructor.atom is not None or not constructor.items:
                    raise CompileError("syntax", "invalid constructor", constructor.span)
                constructors.append(
                    ast.Constructor(
                        constructor.span,
                        identifier(constructor.items[0], constructor=True),
                        tuple(type_syntax(item) for item in constructor.items[1:]),
                    )
                )
            data.append(ast.Data(declaration.span, type_name, parameters, tuple(constructors)))
        else:
            raise CompileError("syntax", f"unknown declaration {kind}", declaration.span)
    return ast.Module(
        form.span, module_name, tuple(imports), tuple(data), tuple(definitions), tuple(exports)
    )
