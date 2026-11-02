"""Typed compilation and incremental artifact reuse through public interfaces."""

import hashlib
from dataclasses import dataclass

from .artifacts import Artifact, Store, digest
from .bytecode import Code, Machine, compile
from .parser import parse, parse_module
from .project import check_expression, check_module, dependency_order
from .transform import erase_annotations, fold
from .types import Type


@dataclass(frozen=True)
class CompiledExpression:
    type: Type
    code: Code

    def run(self, *, fuel: int = 100_000) -> object:
        return Machine(fuel=fuel).run(self.code)


def expression(text: str, *, name: str = "<input>", optimize: bool = True) -> CompiledExpression:
    inferred = check_expression(text, name=name)
    syntax = erase_annotations(parse(text, name))
    return CompiledExpression(inferred, compile(fold(syntax) if optimize else syntax))


@dataclass(frozen=True)
class Compilation:
    order: tuple[str, ...]
    artifacts: dict[str, Artifact]
    reused: tuple[str, ...]


def project(sources: dict[str, str], store: Store | None = None) -> Compilation:
    modules, texts = {}, {}
    for name, text in sorted(sources.items()):
        module = parse_module(text, name)
        if module.name in modules:
            raise ValueError("duplicate module")
        modules[module.name], texts[module.name] = module, text
    order = dependency_order(modules)
    artifacts, reused = {}, []
    for name in order:
        module = modules[name]
        imports = {
            imported.module: artifacts[imported.module].interface for imported in module.imports
        }
        previous = store.read(name) if store else None
        if previous is not None and previous.valid_for(texts[name], imports):
            artifacts[name] = previous
            reused.append(name)
            continue
        checked = check_module(module, imports)
        definitions = tuple(
            (binding.name, compile(erase_annotations(binding.value)))
            for binding in sorted(module.definitions, key=lambda item: item.name)
        )
        artifact = Artifact(
            hashlib.sha256(texts[name].encode()).hexdigest(),
            checked.interface,
            tuple(sorted((key, digest(value.document())) for key, value in imports.items())),
            definitions,
        )
        artifacts[name] = artifact
        if store:
            store.publish(artifact)
    return Compilation(order, artifacts, tuple(reused))
