"""Strategy registries: the dispatch tables of the store.

A *strategy* is a named, pluggable piece of behaviour that the core resolves
at runtime by name: conflict resolution, tombstone expiry, digest computation
and so on. The registry is the only place that maps a name to an implementation
and the only place that knows which name a configuration value may name.

The two rules that make this more than a dictionary:

* a name is registered exactly once; a second registration is an error, never
  a silent overwrite, so a vendored duplicate cannot shadow the real strategy
  at import time;
* an unknown name at *build* time is an error, while an unknown name at
  *dispatch* time raises :class:`UnknownStrategyError` carrying the set of
  names that were registered. That split is what lets a configuration be
  validated without running a strategy, and what makes a misconfigured node
  fail loudly instead of silently using a default.

The default resolution strategy is ``atlas.vclock.resolve`` under the name
``desc-writer``. A second entry, ``asc-writer``, exists for nodes still
running the v2 protocol; the two disagree on concurrent writes, which is
exactly why a mixed-vintage cluster must be fenced, not mixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .errors import ConfigError
from . import vclock


class UnknownStrategyError(ConfigError):
    code = "unknown_strategy"

    def __init__(self, name: str, known: frozenset[str]) -> None:
        self.name = name
        self.known = known
        super().__init__(
            f"unknown strategy {name!r}; registered names: {sorted(known)}"
        )


@dataclass(frozen=True)
class Strategy:
    name: str
    kind: str
    factory: Callable[[], Callable[..., Any]]
    description: str = ""


class Registry:
    """One registry per kind of pluggable behaviour."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._strategies: dict[str, Strategy] = {}

    def register(
        self,
        name: str,
        factory: Callable[[], Callable[..., Any]],
        *,
        description: str = "",
    ) -> None:
        if name in self._strategies:
            raise ConfigError(f"{self.kind} strategy {name!r} is already registered")
        self._strategies[name] = Strategy(name, self.kind, factory, description)

    def names(self) -> frozenset[str]:
        return frozenset(self._strategies)

    def has(self, name: str) -> bool:
        return name in self._strategies

    def resolve(self, name: str | None = None) -> Callable[..., Any]:
        if name is None:
            if len(self._strategies) == 1:
                name = next(iter(self._strategies))
            else:
                raise UnknownStrategyError(repr(name), self.names())
        strategy = self._strategies.get(name)
        if strategy is None:
            raise UnknownStrategyError(name, self.names())
        return strategy.factory()

    def describe(self) -> Mapping[str, str]:
        return {name: strategy.description for name, strategy in self._strategies.items()}


class StrategySet:
    """The registries a node carries, resolved against its configuration."""

    def __init__(self) -> None:
        self.conflict = Registry("conflict")
        self.digest = Registry("digest")
        self.expiry = Registry("expiry")
        #: Schema evolution steps and index projections, registered by
        #: :mod:`atlas.evolution` under ``records:v<a>->v<b>`` and
        #: ``index:<name>``. Empty until that module installs them; see
        #: ``SPEC.md`` section 10.
        self.evolution = Registry("evolution")

    def resolve_conflict(self, name: str) -> Callable[..., Any]:
        return self.conflict.resolve(name)

    def validate(self, config) -> None:
        if not self.conflict.has(config["tie_break"]):
            raise UnknownStrategyError(
                config["tie_break"], self.conflict.names()
            )


def _desc_writer() -> Callable[..., Any]:
    return vclock.resolve


def _asc_writer() -> Callable[..., Any]:
    def resolve_ascending(candidates, *, equal_is_conflict: bool = False):
        options = list(candidates)
        if not options:
            raise vclock.ReadRepairConflictError("<none>", None, None)
        best = options[0]
        for option in options[1:]:
            if vclock.tie_break_key(option[0]) < vclock.tie_break_key(best[0]):
                best = option
        return best

    return resolve_ascending


def _digest_blake2b() -> Callable[..., Any]:
    import hashlib

    def digest(records) -> bytes:
        hasher = hashlib.blake2b(digest_size=16)
        for record in sorted(records, key=lambda item: (item.key, item.generation)):
            hasher.update(f"{record.key}@{record.generation}:{record.lsn}".encode("utf-8"))
        return hasher.digest()

    return digest


def _expiry_grace() -> Callable[..., Any]:
    def expired(record, *, now_ms: int, grace_ms: int) -> bool:
        return (
            record.deleted
            and now_ms - record.written_at >= grace_ms
        )

    return expired


def install_defaults() -> StrategySet:
    strategies = StrategySet()
    strategies.conflict.register(
        "desc-writer", _desc_writer,
        description="concurrent writers: greatest node identifier wins",
    )
    strategies.conflict.register(
        "asc-writer", _asc_writer,
        description="v2 protocol tie-break, kept for fenced mixed clusters",
    )
    strategies.digest.register(
        "blake2b-16", _digest_blake2b,
        description="128-bit digest of the record set, for anti-entropy",
    )
    strategies.expiry.register(
        "grace", _expiry_grace,
        description="tombstones age out after tombstone_grace_ms",
    )
    return strategies


#: The store's own strategies, registered exactly once per process.
STRATEGIES = install_defaults()
