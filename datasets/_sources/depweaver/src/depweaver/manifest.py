"""Strict TOML project manifests, dependency groups and reusable solve profiles."""

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .markers import Target
from .model import Dependency, Policy, Request, canonical, normalize
from .requirements import format, parse


@dataclass(frozen=True)
class Profile:
    name: str
    target: Target
    groups: tuple[str, ...] = ()
    policy: Policy = field(default_factory=Policy)


@dataclass(frozen=True)
class Manifest:
    name: str
    dependencies: tuple[Dependency, ...]
    groups: tuple[tuple[str, tuple[Dependency, ...]], ...]
    profiles: tuple[Profile, ...]

    def roots(self, groups: tuple[str, ...] = ()) -> tuple[Dependency, ...]:
        available = dict(self.groups)
        missing = set(groups) - available.keys()
        if missing:
            raise ValueError("unknown dependency groups: " + ", ".join(sorted(missing)))
        return self.dependencies + tuple(
            dependency for group in sorted(set(groups)) for dependency in available[group]
        )

    def request(
        self,
        profile: str | None = None,
        *,
        groups: tuple[str, ...] = (),
        locked: tuple[tuple[str, str], ...] = (),
        update: frozenset[str] = frozenset(),
    ) -> Request:
        if profile is None:
            return Request(self.roots(groups), locked=locked, update=update)
        choices = {item.name: item for item in self.profiles}
        if profile not in choices:
            raise ValueError("unknown solve profile")
        selected = choices[profile]
        return Request(
            self.roots((*selected.groups, *groups)),
            selected.target,
            locked,
            update,
            selected.policy,
        )

    def document(self) -> dict:
        return {
            "name": self.name,
            "dependencies": [format(dependency) for dependency in self.dependencies],
            "groups": {
                name: [format(dependency) for dependency in dependencies]
                for name, dependencies in self.groups
            },
            "profiles": {
                profile.name: {
                    "target": profile.target.document(),
                    "groups": list(profile.groups),
                    "policy": profile.policy.document(),
                }
                for profile in self.profiles
            },
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical(self.document()).encode()).hexdigest()

    @classmethod
    def load(cls, document: dict) -> "Manifest":
        if not isinstance(document, dict) or set(document) - {
            "name",
            "dependencies",
            "groups",
            "profiles",
        }:
            raise ValueError("unknown manifest fields")
        name = normalize(document["name"])

        def dependencies(values):
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError("dependencies must be an array of requirement strings")
            return tuple(parse(value) for value in values)

        roots = dependencies(document.get("dependencies", []))
        group_table = document.get("groups", {})
        if not isinstance(group_table, dict):
            raise ValueError("groups must be a table")
        groups = tuple(
            (normalize(key), dependencies(values)) for key, values in sorted(group_table.items())
        )
        if len({key for key, values in groups}) != len(groups):
            raise ValueError("dependency group names collide after normalization")
        profiles = []
        for profile_name, values in sorted(document.get("profiles", {}).items()):
            if set(values) - {"target", "groups", "policy"}:
                raise ValueError("unknown profile fields")
            selected_groups = tuple(normalize(value) for value in values.get("groups", []))
            if set(selected_groups) - {key for key, requirements in groups}:
                raise ValueError("profile uses an unknown group")
            profiles.append(
                Profile(
                    normalize(profile_name),
                    Target(**values.get("target", {})),
                    selected_groups,
                    Policy(**values.get("policy", {})),
                )
            )
        if len({profile.name for profile in profiles}) != len(profiles):
            raise ValueError("profile names collide after normalization")
        return cls(name, roots, groups, tuple(profiles))

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        with Path(path).open("rb") as stream:
            document = tomllib.load(stream)
        if set(document) != {"depweaver"}:
            raise ValueError("manifest must contain only a depweaver table")
        return cls.load(document["depweaver"])


def merge(manifests: tuple[Manifest, ...], name: str = "workspace") -> Manifest:
    roots, groups, profiles = [], {}, {}
    for manifest in sorted(manifests, key=lambda item: item.name):
        roots.extend(manifest.dependencies)
        for group, dependencies in manifest.groups:
            key = normalize(manifest.name + "-" + group)
            if key in groups:
                raise ValueError("merged group names collide")
            groups[key] = dependencies
        for profile in manifest.profiles:
            key = normalize(manifest.name + "-" + profile.name)
            if key in profiles:
                raise ValueError("merged profile names collide")
            profiles[key] = Profile(
                key,
                profile.target,
                tuple(normalize(manifest.name + "-" + group) for group in profile.groups),
                profile.policy,
            )
    return Manifest(
        normalize(name),
        tuple(roots),
        tuple(sorted(groups.items())),
        tuple(profiles[key] for key in sorted(profiles)),
    )
