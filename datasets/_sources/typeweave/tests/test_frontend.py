import pytest
from typeweave import CompileError, Interpreter, bytecode, parse, parse_module, pretty, syntax_codec
from typeweave.names import components, free_names


@pytest.mark.parametrize(
    "text,value",
    [
        ("42", 42),
        ("true", True),
        ('"hello"', "hello"),
        ("(+ 2 (* 3 4))", 14),
        ("(let x 3 ((fn y (+ x y)) 4))", 7),
        ("(let r (ref 1) (do (set r 8) (get r)))", 8),
        ("(match (Some 3) ((Some x) (+ x 1)) (None 0))", 4),
        ("(letrec ((f (fn x (if (int-eq x 0) 1 (* x (f (- x 1))))))) (f 5))", 120),
    ],
)
def test_parser_interpreter_and_stack_machine_agree(text, value):
    syntax = parse(text)
    assert Interpreter().evaluate(syntax) == value
    code = bytecode.compile(syntax)
    assert bytecode.Machine().run(code) == value
    assert bytecode.Machine().run(bytecode.Code.load(code.document())) == value
    assert syntax_codec.equivalent(syntax, parse(pretty.expression(syntax)))
    assert syntax_codec.decode(syntax_codec.encode(syntax)) == syntax


def test_sccs_are_dependency_ordered_and_lexically_scoped():
    syntax = parse("(letrec ((use (tuple (id 1) (id true))) (id (fn x x))) use)")
    assert [[binding.name for binding in group] for group in components(syntax.bindings)] == [
        ["id"],
        ["use"],
    ]
    assert free_names(parse("(let x 1 (fn y (+ x y)))")) == {"+"}


def test_modules_format_and_roundtrip_without_typing():
    text = "(module Box (data Box (a) (Box a)) (def id (fn x x)) (export Box id))"
    syntax = parse_module(text)
    assert syntax_codec.equivalent(syntax, parse_module(pretty.module(syntax)))
    assert syntax_codec.decode(syntax_codec.encode(syntax)) == syntax


@pytest.mark.parametrize("text", ["(", ")", "(fn x)", "(let x 1)", "(match 1)", "(set 1)"])
def test_invalid_syntax_has_a_source_span(text):
    with pytest.raises(CompileError) as caught:
        parse(text, "broken.tw")
    assert caught.value.span.source == "broken.tw"
