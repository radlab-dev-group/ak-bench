"""Shared primitive signatures and built-in algebraic data types."""

from .environment import ConstructorInfo, DataInfo, Environment
from .types import BOOL, INT, STRING, UNIT, Constructor, Scheme, Variable, function


def environment() -> Environment:
    integer_binary = Scheme((), function((INT, INT), INT))
    integer_comparison = Scheme((), function((INT, INT), BOOL))
    values = dict.fromkeys(("+", "-", "*", "/"), integer_binary)
    values.update(dict.fromkeys(("<", "<=", ">", ">=", "int-eq"), integer_comparison))
    values.update(
        {
            "not": Scheme((), function((BOOL,), BOOL)),
            "and": Scheme((), function((BOOL, BOOL), BOOL)),
            "or": Scheme((), function((BOOL, BOOL), BOOL)),
            "concat": Scheme((), function((STRING, STRING), STRING)),
            "strlen": Scheme((), function((STRING,), INT)),
            "show-int": Scheme((), function((INT,), STRING)),
            "string-eq": Scheme((), function((STRING, STRING), BOOL)),
            "ignore": Scheme((0,), function((Variable(0),), UNIT)),
        }
    )
    parameter = Variable(1)
    list_type = Constructor("List", (parameter,))
    option_type = Constructor("Option", (parameter,))
    constructors = {
        "Nil": ConstructorInfo("Nil", "List", Scheme((1,), list_type), 0),
        "Cons": ConstructorInfo(
            "Cons", "List", Scheme((1,), function((parameter, list_type), list_type)), 2
        ),
        "None": ConstructorInfo("None", "Option", Scheme((1,), option_type), 0),
        "Some": ConstructorInfo(
            "Some", "Option", Scheme((1,), function((parameter,), option_type)), 1
        ),
    }
    values.update({name: info.scheme for name, info in constructors.items()})
    return Environment(
        values,
        {
            "List": DataInfo("List", (1,), ("Nil", "Cons")),
            "Option": DataInfo("Option", (1,), ("None", "Some")),
        },
        constructors,
    )
