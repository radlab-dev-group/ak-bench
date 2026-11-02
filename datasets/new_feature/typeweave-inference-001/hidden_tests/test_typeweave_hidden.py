"""Soundness, principal types, typed coverage and cross-module integration."""

import json
import os
import random
import subprocess
import sys
from copy import deepcopy

import pytest
from typeweave import (
    CompileError,
    Interpreter,
    build,
    check_expression,
    check_module,
    execute,
    parse,
    parse_module,
    render,
)
from typeweave.compiler import expression as compile_expression
from typeweave.interfaces import Interface, import_into
from typeweave.prelude import environment
from typeweave.source import Span
from typeweave.types import BOOL, INT, Constructor, Scheme, Variable, arrow, encode_scheme
from typeweave.unification import Solver


def inferred(text):
    return render(check_expression(text, name="program.tw"))


def rejects(text, code):
    with pytest.raises(CompileError) as caught:
        check_expression(text, name="program.tw")
    assert caught.value.code == code, caught.value
    assert caught.value.span.source == "program.tw"
    return caught.value


@pytest.mark.parametrize(
    "text,expected",
    [
        ("(fn x x)", "'a -> 'a"),
        ("(fn f (fn x (f x)))", "('a -> 'b) -> 'a -> 'b"),
        ("(fn x (fn y x))", "'a -> 'b -> 'a"),
        ("(let id (fn x x) (tuple (id 1) (id true) (id unit)))", "(Int * Bool * Unit)"),
        ("(let id (fn x x) (let alias id (tuple (alias true) (alias 8))))", "(Bool * Int)"),
        ("(letrec ((use (tuple (id 1) (id true))) (id (fn x x))) use)", "(Int * Bool)"),
        ("(fn x (let y x (tuple y y)))", "'a -> ('a * 'a)"),
        ("(ann (fn x x) (-> a a))", "'a -> 'a"),
        ("(let r (ref 1) (do (set r 4) (get r)))", "Int"),
        ("(list 1 2 3)", "List[Int]"),
        ("(fn xs (match xs (Nil 0) ((Cons head tail) head)))", "List[Int] -> Int"),
        ("(fn pair (match pair ((tuple a b) (tuple b a))))", "('a * 'b) -> ('b * 'a)"),
    ],
)
def test_principal_types(text, expected):
    assert inferred(text) == expected


@pytest.mark.parametrize(
    "text,code",
    [
        ("(fn x (x x))", "infinite-type"),
        ("(fn x (Cons x x))", "infinite-type"),
        ("(if 1 true false)", "type-mismatch"),
        ("(if true 1 false)", "type-mismatch"),
        ("(fn f (tuple (f 1) (f true)))", "type-mismatch"),
        ("(let r (ref (fn x x)) (do (set r (fn x (+ x 1))) ((get r) true)))", "type-mismatch"),
        ("(fn x (let y (fn z x) (do (+ (y unit) 1) (not (y unit)))))", "type-mismatch"),
        ("(let value ((fn x x) (fn x x)) (tuple (value 1) (value true)))", "type-mismatch"),
        ("(letrec ((x (+ x 1))) x)", "recursive-value"),
        ("(letrec ((f (fn x (if true (f 1) (f true))))) f)", "type-mismatch"),
        ("(ann 1 Bool)", "type-mismatch"),
        ("(ann 1 (Int Int))", "type-arity"),
        ("(ann 1 Missing)", "unknown-type"),
        ("missing", "unbound-name"),
        ("(match (Some 1) ((Some x y) x) (_ 0))", "constructor-arity"),
        ("(match 1 ((Missing x) x) (_ 0))", "unknown-constructor"),
    ],
)
def test_rejections_preserve_soundness(text, code):
    rejects(text, code)


def test_solver_composes_substitutions_and_preserves_monomorphic_variables():
    solver = Solver()
    first, second, third = solver.fresh(), solver.fresh(), solver.fresh()
    span = Span.synthetic("constraints.tw")
    solver.unify(first, second, span)
    solver.unify(second, arrow(third, third), span)
    solver.unify(third, INT, span)
    assert solver.apply(first) == arrow(INT, INT)
    shared = solver.fresh()
    scheme = Scheme((1,), arrow(Variable(1), shared))
    left, right = solver.instantiate(scheme), solver.instantiate(scheme)
    assert left.arguments[0] != right.arguments[0]
    assert left.arguments[1] == right.arguments[1] == shared
    scope = environment().extend({"captured": Scheme((), first)})
    assert solver.generalize(first, scope).quantified == ()


def test_generalization_normalizes_the_environment_before_subtracting_free_variables():
    solver = Solver()
    outer, inner = solver.fresh(), solver.fresh()
    scope = environment().extend({"outer": Scheme((), outer)})
    solver.unify(outer, Constructor("Ref", (inner,)), Span.synthetic())
    assert solver.generalize(inner, scope).quantified == ()


def test_type_mismatch_carries_constraint_origin():
    solver = Solver()
    span, origin = Span.synthetic("use.tw"), Span.synthetic("definition.tw")
    with pytest.raises(CompileError) as caught:
        solver.unify(INT, BOOL, span, origin)
    assert caught.value.diagnostic.related[0].span.source == "definition.tw"


@pytest.mark.parametrize(
    "text,code",
    [
        ("(fn x (match x (true 1)))", "non-exhaustive"),
        ("(fn x (match x (_ 1) (true 2)))", "redundant-pattern"),
        ("(fn x (match x (0 1) (1 2)))", "non-exhaustive"),
        ('(fn x (match x ("a" 1) ("b" 2)))', "non-exhaustive"),
        ("(fn x (match x (None 0) ((Some true) 1)))", "non-exhaustive"),
        ("(fn x (match x ((Some _) 1) ((Some true) 2) (None 0)))", "redundant-pattern"),
        ("(fn x (match x ((tuple true _) 1) ((tuple false true) 2)))", "non-exhaustive"),
    ],
)
def test_pattern_matrix_counterexamples(text, code):
    rejects(text, code)


@pytest.mark.parametrize(
    "text",
    [
        "(fn x (match x (None 0) ((Some true) 1) ((Some false) 2)))",
        "(fn x (match x ((tuple true _) 1) ((tuple false true) 2) ((tuple false false) 3)))",
        "(fn x (match x (Nil 0) ((Cons _ Nil) 1) ((Cons _ (Cons _ _)) 2)))",
        "(fn x (match x (unit 0)))",
        "(fn x (match x (0 1) (_ 2)))",
    ],
)
def test_exhaustive_nested_patterns(text):
    assert "->" in inferred(text)


def test_deep_recursive_patterns_are_not_checked_at_a_fixed_depth():
    pattern = "_"
    for _depth in range(35):
        pattern = "(Some " + pattern + ")"
    text = "(fn x (match x (" + pattern + " 1) (_ 0)))"
    assert inferred(text).endswith(" -> Int")


def test_deferred_coverage_sees_types_inferred_in_case_bodies():
    assert inferred("(fn x (match x (value (if value 1 0))))") == "Bool -> Int"
    rejects("(fn x (match x (value (if value 1 0)) (false 2)))", "redundant-pattern")


def test_mutually_recursive_scc_and_completed_scc_polymorphism():
    text = """(letrec (
        (odd (fn n (if (int-eq n 0) false (even (- n 1)))))
        (id (fn x x))
        (even (fn n (if (int-eq n 0) true (odd (- n 1)))))
        (use (tuple (id 1) (id true))))
      (tuple (even 10) (odd 7) use))"""
    assert inferred(text) == "(Bool * Bool * (Int * Bool))"
    assert Interpreter().evaluate(parse(text)) == (True, True, (1, True))


TREE = """(module Trees
  (data Tree (a) (Leaf a) (Node (Tree a) (Tree a)))
  (def sum (fn tree (match tree
    ((Leaf value) value)
    ((Node left right) (+ (sum left) (sum right))))))
  (def tree (Node (Leaf 3) (Node (Leaf 4) (Leaf 5))))
  (export Tree Leaf Node sum tree))"""


def test_nominal_data_recursive_patterns_and_imported_runtime_closures():
    program = build(
        {
            "trees.tw": TREE,
            "main.tw": """(module Main (import Trees trees)
          (def main (trees.sum trees.tree)) (export main))""",
        }
    )
    assert execute(program, "Main", "main") == 12
    imported = program.modules["Trees"].interface.document()
    assert imported["data"]["Tree"]["name"] == "Trees.Tree"


def test_nominally_distinct_same_spelled_types_cannot_unify():
    sources = {
        "a": "(module A (data Box () (Box)) (def box Box) (export Box box))",
        "b": "(module B (data Box () (Box)) (def box Box) (export Box box))",
        "main": (
            "(module Main (import A a) (import B b) (def bad (if true a.box b.box)) (export bad))"
        ),
    }
    with pytest.raises(CompileError) as caught:
        build(sources)
    assert caught.value.code == "type-mismatch"


def test_opaque_family_requires_default_but_can_flow_transitively():
    program = build(
        {
            "a": "(module A (data Secret () (Hidden)) (def value Hidden) (export Secret value))",
            "b": "(module B (import A a) (def pass (fn x a.value)) (export pass))",
            "c": "(module C (import B b) (def main (match (b.pass unit) (_ 7))) (export main))",
        }
    )
    assert execute(program, "C", "main") == 7
    assert "A.Secret" in program.modules["B"].interface.document()["dependencies"]


@pytest.mark.parametrize(
    "text,code",
    [
        ("(module A (def cell (ref (fn x x))) (export cell))", "weak-export"),
        ("(module A (data Hidden () (Hide)) (def value Hide) (export value))", "private-type"),
        ("(module A (export missing))", "unknown-export"),
        ("(module A (def x 1) (export x x))", "duplicate-export"),
        ("(module A (data T (a a) (C a)) (export T C))", "duplicate-parameter"),
        ("(module A (data T (a) (C b)) (export T C))", "unbound-type-variable"),
        ("(module A (data T () (C)) (data T () (D)))", "duplicate-type"),
        ("(module A (data T () (C) (C)))", "duplicate-constructor"),
    ],
)
def test_module_failures(text, code):
    with pytest.raises(CompileError) as caught:
        check_module(parse_module(text))
    assert caught.value.code == code


def test_interface_is_canonical_independent_and_imports_fresh_schemes():
    first = check_module(
        parse_module("(module A (def id (fn x x)) (def hidden (fn y y)) (export id))")
    ).interface
    second = check_module(
        parse_module("(module A (def hidden (fn q q)) (def id (fn value value)) (export id))")
    ).interface
    assert first.payload == second.payload
    document = first.document()
    loaded = Interface.load(deepcopy(document))
    document["values"].clear()
    assert loaded.document() == first.document()
    solver = Solver()
    imported = import_into(environment(), loaded, "lib", solver)
    first_type = solver.instantiate(imported.values["lib.id"])
    second_type = solver.instantiate(imported.values["lib.id"])
    solver.unify(first_type, arrow(INT, INT), Span.synthetic())
    solver.unify(second_type, arrow(BOOL, BOOL), Span.synthetic())
    assert "id" not in imported.values


@pytest.mark.parametrize("damage", ["version", "free", "arity", "constructor"])
def test_malformed_interfaces_are_rejected(damage):
    interface = check_module(parse_module(TREE)).interface.document()
    if damage == "version":
        interface["version"] = 999
    elif damage == "free":
        interface["values"]["sum"] = encode_scheme(Scheme((), Variable(100)))
    elif damage == "arity":
        interface["values"]["sum"] = encode_scheme(Scheme((), Constructor("Int", (INT,))))
    else:
        interface["constructors"]["Leaf"]["owner"] = "Missing.Type"
    with pytest.raises(ValueError):
        Interface.load(interface)


def test_exported_interface_survives_a_fresh_interpreter(tmp_path):
    interface = check_module(parse_module("(module A (def id (fn x x)) (export id))")).interface
    path = tmp_path / "interface.json"
    path.write_text(json.dumps(interface.document()))
    script = """
import json,sys
from typeweave.interfaces import Interface, import_into
from typeweave.prelude import environment
from typeweave.inference import Inferencer
from typeweave.parser import parse
from typeweave.types import render
checker = Inferencer()
interface = Interface.load(json.load(open(sys.argv[1])))
scope = import_into(environment(), interface, 'a', checker.solver)
term = checker.expression(parse('(tuple (a.id 1) (a.id true))'), scope)
checker.finish()
print(render(checker.solver.apply(term)))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert completed.stdout.strip() == "(Int * Bool)"


@pytest.mark.parametrize("seed", range(25))
def test_generated_well_typed_programs_match_typed_vm_and_interpreter(seed):
    randomizer = random.Random(seed)
    value = randomizer.randint(-20, 20)
    text, expected = str(value), value
    for depth in range(10):
        amount = randomizer.randint(-9, 9)
        choice = randomizer.randrange(4)
        if choice == 0:
            text, expected = f"(+ {text} {amount})", expected + amount
        elif choice == 1:
            text = f"(let id{depth} (fn item item) (id{depth} {text}))"
        elif choice == 2:
            text = f"(match (Some {text}) ((Some value) value) (None 0))"
        else:
            text = (
                f"(let cell{depth} (ref {text}) "
                f"(do (set cell{depth} (+ (get cell{depth}) {amount})) (get cell{depth})))"
            )
            expected += amount
    assert inferred(text) == "Int"
    assert Interpreter().evaluate(parse(text)) == expected
    compiled = compile_expression(text)
    assert render(compiled.type) == "Int"
    assert compiled.run() == expected
    rejects(f"(+ {text} false)", "type-mismatch")


def test_typed_compiler_and_editor_use_the_same_principal_types():
    from typeweave.compiler import expression
    from typeweave.service import Service

    text = "(let id (fn x x) (tuple (id 4) (id true)))"
    compiled = expression(text)
    assert render(compiled.type) == "(Int * Bool)"
    assert compiled.run() == (4, True)
    service = Service()
    service.open("typed.tw", text)
    inspection = service.inspect("typed.tw")
    assert inspection.type == "(Int * Bool)"
    assert inspection.diagnostics == ()


def test_incremental_artifacts_bind_import_interfaces_and_survive_disk_restore(tmp_path):
    from typeweave.artifacts import Artifact, Store
    from typeweave.package import Package, Unit

    first = Package(
        "Project",
        (
            Unit("a.tw", "(module A (def x 1) (export x))"),
            Unit("b.tw", "(module B (import A a) (def y a.x) (export y))"),
        ),
    )
    store = Store(tmp_path / "artifacts")
    initial = first.compile(store)
    assert initial.order == ("A", "B")
    assert initial.reused == ()
    assert first.compile(Store(store.root)).reused == ("A", "B")
    # A value change with the same public type preserves B's cached artifact.
    second = Package("Project", (Unit("a.tw", "(module A (def x 2) (export x))"), first.units[1]))
    assert second.compile(store).reused == ("B",)
    # A public type change invalidates B even though its own source is identical.
    third = Package("Project", (Unit("a.tw", "(module A (def x true) (export x))"), first.units[1]))
    changed = third.compile(store)
    assert changed.reused == ()
    assert (
        Artifact.load(changed.artifacts["B"].document()).document()
        == changed.artifacts["B"].document()
    )
    assert store.inventory()


def test_exported_type_and_constructor_can_share_the_same_spelling():
    result = build({"box.tw": "(module Boxes (data Box (a) (Box a)) (export Box))"})
    document = result.modules["Boxes"].interface.document()
    assert "Box" in document["data"]
    assert "Box" in document["values"]
    assert "Box" in document["constructors"]


def test_module_bytecode_linker_preserves_nominal_constructors_and_recursive_closures(tmp_path):
    from typeweave.artifacts import Store
    from typeweave.compiler import project
    from typeweave.linker import Runtime

    sources = {
        "a.tw": (
            "(module A (data Box (a) (Box a)) "
            "(def unbox (fn value (match value ((Box inner) inner)))) "
            "(export Box unbox))"
        ),
        "b.tw": (
            "(module B (import A a) (def answer (a.unbox (a.Box 42))) "
            "(def twice (fn x (+ x x))) (export answer twice))"
        ),
    }
    checked = build(sources)
    compilation = project(sources, Store(tmp_path / "cache"))
    runtime = Runtime()
    assert runtime.link(checked, compilation.artifacts) == ("A", "B")
    assert runtime.exported("B", "answer") == 42
    assert runtime.call("B", "twice", 7) == 14
    assert runtime.fuel < 100_000
