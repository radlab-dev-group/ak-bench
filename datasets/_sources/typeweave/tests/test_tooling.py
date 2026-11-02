from dataclasses import replace

import pytest
from typeweave.alpha import equivalent, normalize
from typeweave.analysis import Effect, calls, effects, warnings
from typeweave.artifacts import Store
from typeweave.buffer import Buffer, Coordinate, Edit
from typeweave.bytecode import Machine, compile
from typeweave.diagnostic_store import Diagnostics, load
from typeweave.diagnostics import Diagnostic
from typeweave.inspection import disassemble, free_loads, instructions_at, metrics
from typeweave.interpreter import Interpreter
from typeweave.names import free_names
from typeweave.package import Package, Unit, relative_name
from typeweave.parser import parse
from typeweave.service import Service
from typeweave.source import Source
from typeweave.validation import validate


def test_alpha_conversion_avoids_capture_and_preserves_semantics():
    syntax = parse("(fn x (tuple x _bound_0))")
    normalized = normalize(syntax)
    assert free_names(normalized) == {"_bound_0"}
    assert normalized.parameter != "_bound_0"
    assert equivalent(syntax, parse("(fn y (tuple y _bound_0))"))
    assert not equivalent(syntax, parse("(fn y (tuple y _bound_1))"))
    program = parse("(let x 4 ((fn x (+ x 1)) x))")
    assert Interpreter().evaluate(normalize(program)) == Interpreter().evaluate(program) == 5


def test_utf16_edits_are_atomic_and_roundtrip():
    buffer = Buffer("emoji.tw", "a😀b\nxyz", 1)
    assert buffer.offset(Coordinate(0, 3)) == 2
    assert buffer.coordinate(2) == Coordinate(0, 3)
    before = buffer.document()
    with pytest.raises(ValueError, match="surrogate"):
        buffer.apply((Edit(Coordinate(0, 1), Coordinate(0, 2), "x"),), 2)
    assert buffer.document() == before
    with pytest.raises(ValueError, match="overlapping"):
        buffer.apply(
            (
                Edit(Coordinate(0, 0), Coordinate(0, 3), "x"),
                Edit(Coordinate(0, 1), Coordinate(0, 4), "y"),
            ),
            2,
        )
    assert buffer.document() == before
    buffer.apply(
        (
            Edit(Coordinate(0, 1), Coordinate(0, 3), "Q"),
            Edit(Coordinate(1, 0), Coordinate(1, 3), "R"),
        ),
        2,
    )
    assert buffer.text == "aQb\nR"
    assert Buffer.load(buffer.document()).document() == buffer.document()


def test_external_ast_validation_rejects_bad_shapes_and_resource_limits():
    syntax = parse("(fn x (+ x 1))")
    validate(syntax)
    with pytest.raises(ValueError, match="name"):
        validate(replace(syntax, parameter=""))
    with pytest.raises(ValueError, match="resource"):
        validate(syntax, max_nodes=2)
    with pytest.raises(ValueError, match="expression"):
        validate(replace(syntax, body=123))


def test_effects_warnings_and_call_analysis():
    assert effects(parse("(fn x (ref x))")) == Effect.PURE
    assert effects(parse("(do (ref 1) (get cell) (set cell 2))")) == (
        Effect.ALLOCATE | Effect.READ | Effect.WRITE
    )
    assert {item.code for item in warnings(parse("(let unused 1 (fn x 2))"))} == {
        "unused-binding",
        "unused-parameter",
    }
    call = calls(parse("(fn x (if true (f x) (g x)))"))
    assert {item.callee for item in call if item.tail} == {"f", "g"}


def test_bytecode_inspection_tracks_scopes_and_nested_code():
    syntax = parse("(let x 2 ((fn y (+ x y)) external))")
    code = compile(syntax)
    assert free_loads(code) == ("+", "external")
    assert "closure" in disassemble(code)
    assert metrics(code)["maximum_nesting"] == 1
    assert instructions_at(code, syntax.span)
    closed = compile(parse("(let x 2 ((fn y (+ x y)) 3))"))
    assert Machine().run(closed) == 5


def test_editor_checkpoints_parse_cache_and_versioned_diagnostics():
    service = Service()
    service.open("x.tw", "(fn x x)", 1)
    assert service.parsed("x.tw") is service.parsed("x.tw")
    assert service.inspect("x.tw", typing=False).type is None
    assert Service.restore(service.checkpoint()).checkpoint() == service.checkpoint()
    service.edit("x.tw", (Edit(Coordinate(0, 6), Coordinate(0, 7), "y"),), 2)
    assert service.buffers["x.tw"].text == "(fn x y)"
    service.close("x.tw")
    assert not service.syntax
    source = Source("abc", "x.tw")
    diagnostic = Diagnostic("example", "bad input", source.span(0, 2))
    assert load(diagnostic.document()) == diagnostic
    diagnostics = Diagnostics()
    diagnostics.publish(source, 1, (diagnostic, diagnostic))
    assert diagnostics.counts() == {"example": 1}
    restored = Diagnostics.restore(diagnostics.document(), {source.name: source})
    assert diagnostics.delta(restored) == ()
    with pytest.raises(ValueError, match="stale"):
        diagnostics.clear(source, 1)
    diagnostics.clear(source, 2)
    assert len(diagnostics.delta(restored)) == 1


def test_source_package_graph_roundtrip_and_invalidation(tmp_path):
    first = Package(
        "Project",
        (
            Unit("a.tw", "(module A (def x 1) (export x))"),
            Unit("b.tw", "(module B (import A a) (def y a.x) (export y))"),
        ),
    )
    first.materialize(tmp_path / "sources")
    discovered = Package.discover(tmp_path / "sources", "Project")
    assert discovered.fingerprint == first.fingerprint
    first.write(tmp_path / "project.json")
    assert Package.read(tmp_path / "project.json").fingerprint == first.fingerprint
    assert first.graph.levels() == (("A",), ("B",))
    second = Package("Project", (Unit("a.tw", "(module A (def x 2) (export x))"), first.units[1]))
    assert first.compare(second).affected == ("A", "B")
    assert first.plan(Store(tmp_path / "cache"))["affected"] == ["A", "B"]
    assert first.report()["modules"]["A"]["definitions"] == 1
    with pytest.raises(FileExistsError):
        first.materialize(tmp_path / "sources")


@pytest.mark.parametrize(
    "path", ("../escape.tw", "/abs.tw", "a//b.tw", "a/./b.tw", "a\\b.tw", "a.txt")
)
def test_source_package_paths_are_portable(path):
    with pytest.raises(ValueError):
        relative_name(path)
