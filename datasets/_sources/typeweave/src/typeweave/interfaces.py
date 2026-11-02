"""Implement independent, canonical, closed module type interfaces.

Interface JSON must contain version, module, exported schemes, public data and
constructor metadata. No mutable Solver or Environment objects may be retained.
Reject exports with free monomorphic variables ('weak-export'); opaque hidden
constructors must not become accessible to importers. Read SPEC.md for rules.
"""

from dataclasses import dataclass

from . import ast
from .environment import Environment


@dataclass(frozen=True)
class Interface:
    module: str
    payload: str

    def document(self) -> dict:
        import json

        return json.loads(self.payload)

    @classmethod
    def load(cls, document: dict) -> "Interface":
        raise NotImplementedError("validate version, closure, arities and constructor ownership")


def export(module: ast.Module, environment: Environment, solver) -> Interface:
    raise NotImplementedError("freeze canonical alpha-normalized public interface")


def import_into(environment: Environment, interface: Interface, alias: str, solver) -> Environment:
    raise NotImplementedError(
        "freshen quantified identities and install only qualified public names"
    )
