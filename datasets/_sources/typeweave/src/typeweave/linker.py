"""Link typed source modules for execution through the independent bytecode VM."""

from dataclasses import dataclass

from .artifacts import Artifact, digest
from .bytecode import CompiledClosure, Machine, compile
from .diagnostics import EvaluationError
from .interpreter import UNINITIALIZED, Primitive, Scope, builtins, data_scope
from .names import components
from .project import Build, dependency_order
from .source import Span


@dataclass(frozen=True)
class LinkedModule:
    name: str
    scope: Scope
    values: tuple[str, ...]
    constructors: tuple[tuple[str, str], ...]

    def exported(self, name: str) -> object:
        if name not in self.values:
            raise KeyError("binding is not exported: " + name)
        return self.scope.get(name, Span.synthetic(self.name))


class Runtime:
    def __init__(self, *, fuel: int = 100_000) -> None:
        if type(fuel) is not int or fuel < 1:
            raise ValueError("runtime fuel must be positive")
        self.machine = Machine(fuel=fuel)
        self.modules: dict[str, LinkedModule] = {}

    @property
    def fuel(self) -> int:
        return self.machine.fuel

    def link(self, build: Build, artifacts: dict[str, Artifact] | None = None) -> tuple[str, ...]:
        if self.modules:
            raise ValueError("runtime already has linked modules")
        syntax = {name: checked.syntax for name, checked in build.modules.items()}
        if dependency_order(syntax) != build.order:
            raise ValueError("build dependency order mismatch")
        artifacts = artifacts or {}
        if artifacts.keys() - build.modules.keys():
            raise ValueError("artifact references an unknown module")
        linked = {}
        for name in build.order:
            checked = build.modules[name]
            interface = checked.interface.document()
            scope = builtins()
            canonical = {}
            for imported in checked.syntax.imports:
                dependency = linked[imported.module]
                for exported in dependency.values:
                    scope.values[imported.alias + "." + exported] = dependency.exported(exported)
                for exported, original in dependency.constructors:
                    canonical[imported.alias + "." + exported] = original
            canonical.update(data_scope(checked.syntax, scope))
            artifact = artifacts.get(name)
            if artifact is not None:
                if artifact.interface.document() != interface:
                    raise ValueError("artifact interface differs from checked module")
                dependencies = tuple(
                    sorted(
                        (item.module, digest(build.modules[item.module].interface.document()))
                        for item in checked.syntax.imports
                    )
                )
                if artifact.dependencies != tuple(sorted(set(dependencies))):
                    raise ValueError("artifact dependency fingerprints differ from build")
                code = dict(artifact.definitions)
                if set(code) != {binding.name for binding in checked.syntax.definitions}:
                    raise ValueError("artifact definitions differ from checked module")
            else:
                code = {
                    binding.name: compile(binding.value) for binding in checked.syntax.definitions
                }
            for definition in checked.syntax.definitions:
                scope.values[definition.name] = UNINITIALIZED
            self.machine.constructors = canonical
            for group in components(checked.syntax.definitions):
                for definition in group:
                    scope.values[definition.name] = self.machine.run(code[definition.name], scope)
            public_constructors = tuple(
                sorted((exported, canonical[exported]) for exported in interface["constructors"])
            )
            linked[name] = LinkedModule(
                name, scope, tuple(sorted(interface["values"])), public_constructors
            )
        self.modules = linked
        return build.order

    def exported(self, module: str, name: str) -> object:
        return self.modules[module].exported(name)

    def call(self, module: str, name: str, *arguments: object) -> object:
        value = self.exported(module, name)
        span = Span.synthetic(module + "." + name)
        for argument in arguments:
            if isinstance(value, CompiledClosure):
                self.machine.constructors = value.constructors
                value = self.machine.run(value.code, value.scope.child({value.parameter: argument}))
            elif isinstance(value, Primitive):
                try:
                    value = value.apply(argument)
                except (ValueError, TypeError, ZeroDivisionError) as error:
                    raise EvaluationError(str(error), span) from error
            else:
                raise EvaluationError("export is not a function at this argument", span)
        return value

    def inventory(self) -> dict:
        return {
            "fuel_remaining": self.fuel,
            "modules": {
                name: {"values": list(module.values), "constructors": dict(module.constructors)}
                for name, module in sorted(self.modules.items())
            },
        }
