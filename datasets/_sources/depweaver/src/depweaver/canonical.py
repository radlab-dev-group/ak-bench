"""Canonical lockfile form and the canonical digest — declared, not implemented.

The contract is SPEC.md, section "Lockfile canonical form and proofs", with
the ordering rules spelled out in docs/lockfile-canonical-form.md and the
reasons in docs/adr/. Every function below that would do work raises
NotImplementedError. The signatures are the public surface; keep them.
"""

from .markers import Marker
from .model import Dependency, Resolution
from .versions import Version

CANONICAL_VERSION = 1


def canonical_version(version: Version | str) -> str:
    """Render a version without its build metadata."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")


def canonical_extras(extras) -> tuple[str, ...]:
    """Normalise and order a set of extras."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")


def canonical_marker(marker: Marker | str) -> str:
    """Render a marker in its canonical text (docs/lockfile-canonical-form.md, rule M)."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")


def canonical_dependency(dependency: Dependency) -> dict:
    """Canonical row of one dependency declaration."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")


def active_edges(resolution: Resolution) -> dict[str, tuple[str, ...]]:
    """Map each selected package to the selected packages it actively depends on."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")


def layers(resolution: Resolution) -> dict[str, int]:
    """Height of every selected package in the condensed active dependency graph."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")


def canonical_order(value: object) -> tuple[tuple[str, str], ...]:
    """The (name, version) pairs of a resolution or lockfile in canonical order."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")


def canonical_document(value: object) -> dict:
    """The canonical JSON document of a resolution or lockfile."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")


def lock_digest(value: object) -> str:
    """SHA-256 of the canonical JSON serialisation of ``canonical_document``."""
    raise NotImplementedError("canonical form is declared in SPEC.md but not implemented")
