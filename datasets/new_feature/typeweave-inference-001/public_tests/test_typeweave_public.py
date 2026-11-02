import pytest
from typeweave import CompileError, check_expression, render


def test_identity_is_polymorphic_at_let():
    assert render(check_expression("(let id (fn x x) (tuple (id 1) (id true)))")) == "(Int * Bool)"


def test_mutable_identity_does_not_generalize():
    with pytest.raises(CompileError) as caught:
        check_expression("(let r (ref (fn x x)) (do (set r (fn x (+ x 1))) ((get r) true)))")
    assert caught.value.code == "type-mismatch"


def test_bool_match_requires_both_values():
    with pytest.raises(CompileError) as caught:
        check_expression("(fn x (match x (true 1)))")
    assert caught.value.code == "non-exhaustive"
