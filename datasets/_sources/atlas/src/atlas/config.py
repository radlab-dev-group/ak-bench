"""Configuration, assembled from five layers with a documented precedence.

Layers, lowest to highest:

1. ``DEFAULTS`` in this module;
2. the **configuration file** (``ATLAS_CONFIG`` or ``./atlas.toml``);
3. the **profile** named by ``ATLAS_PROFILE``, read from the ``[profile.*]``
   tables of that same file;
4. **environment** variables named ``ATLAS_<UPPER_SNAKE>``;
5. **explicit overrides** passed in code to :class:`ConfigBuilder`.

Two rules make this more than an ordered dictionary merge, and both are
part of the contract:

* a profile beats the bare file but *loses* to the environment, so an
  operator can always override a named profile without editing it;
* a layer contributes a key only when it **names** that key. An empty string
  from the environment is a value, not an absence: it wins over every lower
  layer and is then validated, so an unset variable must be omitted rather
  than set to "".

:func:`explain` reports which layer won for every key, which is the only
supported way to answer "why is this my quorum" without guessing.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .errors import ConfigError

ENV_PREFIX = "ATLAS_"
CONFIG_FILE_ENV = "ATLAS_CONFIG"
PROFILE_ENV = "ATLAS_PROFILE"
DEFAULT_CONFIG_NAME = "atlas.toml"

#: Every recognised key with its default value and the type it must hold.
DEFAULTS: dict[str, Any] = {
    "node_id": "node-0",
    "data_dir": "./atlas-data",
    "shards": 4,
    "replication_factor": 3,
    "read_consistency": 2,
    "write_consistency": 2,
    "vnodes": 64,
    "epoch": 1,
    "fsync_on_commit": True,
    "torn_tail_repair": True,
    "compaction_lsn_boundary": "exclusive",
    "read_repair_enabled": True,
    "tie_break": "desc-writer",
    "generation_check": "strict",
    "tombstone_grace_ms": 604_800_000,
    "max_wal_bytes": 8 * 1024 * 1024,
    "migration_batch": 256,
    "lineage_enabled": True,
    "audit_enabled": False,
}

#: The types a key is allowed to hold. Anything else is a configuration error
#: rather than a truthiness accident.
_TYPES: dict[str, type | tuple[type, ...]] = {
    "node_id": str,
    "data_dir": str,
    "shards": int,
    "replication_factor": int,
    "read_consistency": int,
    "write_consistency": int,
    "vnodes": int,
    "epoch": int,
    "fsync_on_commit": bool,
    "torn_tail_repair": bool,
    "compaction_lsn_boundary": str,
    "read_repair_enabled": bool,
    "tie_break": str,
    "generation_check": str,
    "tombstone_grace_ms": int,
    "max_wal_bytes": int,
    "migration_batch": int,
    "lineage_enabled": bool,
    "audit_enabled": bool,
}

_LSN_BOUNDARIES = ("exclusive", "inclusive")
_GENERATION_CHECKS = ("strict", "permissive")
_TIE_BREAKS = ("desc-writer", "asc-writer")


@dataclass(frozen=True)
class Config:
    """The effective configuration of one node, plus the provenance of each key."""

    values: Mapping[str, Any]
    sources: Mapping[str, str] = field(default_factory=dict)

    def get(self, key: str, fallback: Any = None) -> Any:
        return self.values.get(key, fallback)

    def __getitem__(self, key: str) -> Any:
        try:
            return self.values[key]
        except KeyError as exc:
            raise ConfigError(f"unknown configuration key: {key}") from exc

    def source_of(self, key: str) -> str:
        return self.sources.get(key, "default")

    def replaced(self, **updates: Any) -> "Config":
        merged = dict(self.values)
        merged.update(updates)
        return build(values=merged)


def _coerce(key: str, raw: Any, *, origin: str) -> Any:
    if key not in DEFAULTS:
        raise ConfigError(f"unknown configuration key {key!r} from {origin}")
    expected = _TYPES[key]
    if isinstance(raw, str) and expected is not str:
        text = raw.strip()
        lowered = text.lower()
        if expected is bool:
            if lowered in ("1", "true", "yes", "on"):
                raw = True
            elif lowered in ("0", "false", "no", "off"):
                raw = False
            else:
                raise ConfigError(f"{key!r} from {origin} is not a boolean: {raw!r}")
        elif expected is int:
            try:
                raw = int(text, 0)
            except ValueError as exc:
                raise ConfigError(f"{key!r} from {origin} is not an integer: {raw!r}") from exc
    if not isinstance(raw, expected) or isinstance(raw, bool) and expected is int:
        raise ConfigError(
            f"{key!r} from {origin} must be {expected.__name__}, got {type(raw).__name__}"
        )
    return raw


def _parse_tomlish(path: pathlib.Path) -> dict[str, Any]:
    """A minimal ``key = value`` reader with ``[profile.name]`` sections.

    Deliberately tiny: the seed has no TOML dependency. Quoted strings, bare
    ints, booleans and ``_``-separated numeric literals are understood;
    anything else is a configuration error naming the offending line.
    """

    if not path.exists():
        return {}
    document: dict[str, Any] = {}
    profiles: dict[str, dict[str, Any]] = {}
    section: str | None = None
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            header = line[1:-1].strip()
            if header.startswith("profile."):
                section = header.split(".", 1)[1]
                profiles.setdefault(section, {})
            elif header == "DEFAULT":
                section = None
            else:
                raise ConfigError(f"{path}:{lineno}: unknown section [{header}]")
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{lineno}: expected key = value, got {line!r}")
        name, _, raw_value = line.partition("=")
        name = name.strip()
        value = raw_value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            parsed: Any = value[1:-1]
        elif value.lower() in ("true", "false"):
            parsed = value.lower() == "true"
        else:
            literal = value.replace("_", "")
            try:
                parsed = int(literal, 0)
            except ValueError:
                parsed = value
        target = document if section is None else profiles[section]
        target[name] = parsed
    document["__profiles__"] = profiles
    return document


def build(
    *,
    values: Mapping[str, Any] | None = None,
    path: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    profile: str | None = None,
) -> Config:
    """Assemble the effective configuration, honouring the five layers."""

    environment = dict(os.environ if env is None else env)
    effective = dict(DEFAULTS)
    sources = {key: "default" for key in DEFAULTS}

    document = _parse_tomlish(pathlib.Path(path or environment.get(CONFIG_FILE_ENV, DEFAULT_CONFIG_NAME)))
    profiles = document.pop("__profiles__", {})
    for key, raw in document.items():
        effective[key] = _coerce(key, raw, origin="file")
        sources[key] = "file"

    named = profile or environment.get(PROFILE_ENV, "")
    if named:
        if named not in profiles:
            raise ConfigError(f"profile {named!r} is not declared in the configuration file")
        for key, raw in profiles[named].items():
            effective[key] = _coerce(key, raw, origin=f"profile:{named}")
            sources[key] = f"profile:{named}"

    for key in DEFAULTS:
        name = ENV_PREFIX + key.upper()
        if name in environment:
            effective[key] = _coerce(key, environment[name], origin=f"env:{name}")
            sources[key] = f"env:{name}"

    if values:
        for key, raw in values.items():
            effective[key] = _coerce(key, raw, origin="explicit")
            sources[key] = "explicit"

    config = Config(values=effective, sources=sources)
    _validate(config)
    return config


def _validate(config: Config) -> None:
    values = config.values
    if values["shards"] < 1:
        raise ConfigError("shards must be positive")
    if values["vnodes"] < 1:
        raise ConfigError("vnodes must be positive")
    if values["replication_factor"] < 1:
        raise ConfigError("replication_factor must be positive")
    if values["write_consistency"] + values["read_consistency"] <= values["replication_factor"]:
        raise ConfigError(
            "read_consistency + write_consistency must exceed replication_factor, got "
            f"{values['read_consistency']} + {values['write_consistency']} <= "
            f"{values['replication_factor']}"
        )
    if values["epoch"] < 1:
        raise ConfigError("epoch must be at least one")
    if values["compaction_lsn_boundary"] not in _LSN_BOUNDARIES:
        raise ConfigError(
            f"compaction_lsn_boundary must be one of {_LSN_BOUNDARIES}, "
            f"got {values['compaction_lsn_boundary']!r}"
        )
    if values["generation_check"] not in _GENERATION_CHECKS:
        raise ConfigError(
            f"generation_check must be one of {_GENERATION_CHECKS}, "
            f"got {values['generation_check']!r}"
        )
    if values["tie_break"] not in _TIE_BREAKS:
        raise ConfigError(f"tie_break must be one of {_TIE_BREAKS}, got {values['tie_break']!r}")
    if values["tombstone_grace_ms"] < 0:
        raise ConfigError("tombstone_grace_ms must not be negative")


def explain(config: Config) -> list[tuple[str, Any, str]]:
    """``(key, value, winning layer)`` for every key, sorted."""

    return sorted(
        (key, value, config.sources.get(key, "default")) for key, value in config.values.items()
    )


class ConfigBuilder:
    """Collect explicit overrides before assembling; layer five of five."""

    def __init__(self, *, path: str | os.PathLike[str] | None = None) -> None:
        self._path = path
        self._explicit: dict[str, Any] = {}
        self._profile: str | None = None

    def set(self, key: str, value: Any) -> "ConfigBuilder":
        self._explicit[key] = value
        return self

    def profile(self, name: str) -> "ConfigBuilder":
        self._profile = name
        return self

    def build(self, *, env: Mapping[str, str] | None = None) -> Config:
        return build(values=self._explicit, path=self._path, env=env, profile=self._profile)
