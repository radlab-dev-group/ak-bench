"""Environment observation restricted to an explicit allowlist (plan 10.1).

The process environment is never scanned. Only variables named in a plugin
descriptor are read, and a sensitive variable is reduced to ``is_set`` so a
secret value cannot reach a manifest, a report or an export.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from akbench.core.errors import DescriptorError
from akbench.descriptors.plugin import ConfiguredValue, ObservedEnv
from akbench.descriptors.statuses import ValueSource, VerificationStatus


def coerce(value: str, entry: ObservedEnv) -> str | int | float | bool:
    """Convert a raw environment string to the declared type."""
    from akbench.descriptors.plugin import EnvType

    if entry.type is EnvType.STRING:
        return value
    if entry.type is EnvType.BOOLEAN:
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{entry.name}: {value!r} is not a boolean")
    if entry.type is EnvType.INTEGER:
        return int(value)
    if entry.type is EnvType.FLOAT:
        return float(value)
    return value  # lists stay raw strings; the consumer splits them


def observe_env(
    entries: list[ObservedEnv],
    environ: Mapping[str, str] | None = None,
) -> list[ConfiguredValue]:
    """Read only the allowlisted variables from ``environ``.

    Secrets are reported with ``is_set`` and no value content; everything else
    carries the parsed value plus its provenance.
    """
    env = os.environ if environ is None else environ
    observed: list[ConfiguredValue] = []

    for entry in entries:
        if not entry.observed:
            continue
        raw = env.get(entry.name)
        is_set = raw is not None

        if entry.sensitive:
            observed.append(
                ConfiguredValue(
                    name=entry.name,
                    requested_value=None,
                    configured_value=None,
                    effective_value=None,
                    observed_value=None,
                    is_set=is_set,
                    verification_status=(
                        VerificationStatus.UNVERIFIED
                        if is_set
                        else VerificationStatus.NOT_CONFIGURED
                    ),
                    value_source=ValueSource.ENVIRONMENT if is_set else ValueSource.UNKNOWN,
                    note="sensitive: presence recorded, value never read",
                )
            )
            continue

        if raw is None:
            observed.append(
                ConfiguredValue(
                    name=entry.name,
                    configured_value=entry.default,
                    observed_value=None,
                    is_set=False,
                    verification_status=VerificationStatus.NOT_CONFIGURED,
                    value_source=(
                        ValueSource.DEFAULT if entry.default is not None else ValueSource.UNKNOWN
                    ),
                )
            )
            continue

        try:
            parsed: str | int | float | bool | None = coerce(raw, entry)
        except ValueError as exc:
            observed.append(
                ConfiguredValue(
                    name=entry.name,
                    observed_value=None,
                    is_set=True,
                    verification_status=VerificationStatus.RUNTIME_ERROR,
                    value_source=ValueSource.ENVIRONMENT,
                    note=str(exc),
                )
            )
            continue

        observed.append(
            ConfiguredValue(
                name=entry.name,
                observed_value=parsed,
                effective_value=parsed,
                is_set=True,
                verification_status=VerificationStatus.UNVERIFIED,
                value_source=ValueSource.ENVIRONMENT,
            )
        )

    return observed


def allowed_names(entries: list[ObservedEnv]) -> set[str]:
    """Names that may be read, for guards that build a child environment."""
    return {entry.name for entry in entries if entry.observed}


def assert_allowlisted(entries: list[ObservedEnv], names: list[str]) -> None:
    """Fail loudly when code asks for a variable no descriptor declared."""
    permitted = allowed_names(entries)
    offenders = sorted(set(names) - permitted)
    if offenders:
        raise DescriptorError(
            "environment variables are not allowlisted and must not be observed: "
            + ", ".join(offenders)
        )


def redact(values: list[ConfiguredValue]) -> list[dict[str, object]]:
    """Serialize observations without ever exposing a secret value."""
    return [value.redacted() for value in values]
