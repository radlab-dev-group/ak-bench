"""ENV allowlist behaviour (plan 10.1): observe only what is declared, never secrets."""

from __future__ import annotations

import pytest

from akbench.core.errors import DescriptorError
from akbench.descriptors import (
    ConfiguredValue,
    ObservedEnv,
    VerificationStatus,
    assert_allowlisted,
    observe_env,
    redact,
)


def _flag(name: str = "FEATURE_ENABLED", **overrides: object) -> ObservedEnv:
    base: dict[str, object] = {
        "name": name,
        "type": "boolean",
        "observed": True,
        "controllable": True,
    }
    base.update(overrides)
    return ObservedEnv(**base)


def test_only_allowlisted_variables_are_read() -> None:
    entries = [_flag()]
    values = observe_env(entries, environ={"FEATURE_ENABLED": "1", "UNDECLARED": "x"})
    assert [value.name for value in values] == ["FEATURE_ENABLED"]


def test_unobserved_entries_are_skipped_entirely() -> None:
    entries = [_flag(observed=False)]
    assert observe_env(entries, environ={"FEATURE_ENABLED": "1"}) == []


def test_sensitive_value_is_never_captured() -> None:
    entries = [
        ObservedEnv(
            name="API_TOKEN",
            type="string",
            role="secret",
            observed=True,
            controllable=False,
            sensitive=True,
        )
    ]
    values = observe_env(entries, environ={"API_TOKEN": "super-secret"})
    value = values[0]
    assert value.is_set is True
    assert value.observed_value is None
    assert value.requested_value is None
    serialized = redact(values)[0]
    assert "super-secret" not in str(serialized)
    assert serialized["is_set"] is True


def test_missing_sensitive_variable_stays_not_configured() -> None:
    entries = [ObservedEnv(name="API_TOKEN", type="string", role="secret", observed=True)]
    value = observe_env(entries, environ={})[0]
    assert value.is_set is False
    assert value.verification_status is VerificationStatus.NOT_CONFIGURED


def test_boolean_coercion_and_type_errors() -> None:
    values = observe_env([_flag()], environ={"FEATURE_ENABLED": "yes"})
    assert values[0].observed_value is True
    assert values[0].verification_status is VerificationStatus.UNVERIFIED

    values = observe_env([_flag()], environ={"FEATURE_ENABLED": "maybe"})
    assert values[0].verification_status is VerificationStatus.RUNTIME_ERROR
    assert "not a boolean" in values[0].note
    assert values[0].observed_value is None


def test_missing_variable_falls_back_to_declared_default() -> None:
    entries = [_flag(default="true")]
    value = observe_env(entries, environ={})[0]
    assert value.is_set is False
    assert value.verification_status is VerificationStatus.NOT_CONFIGURED


def test_integer_and_float_coercion() -> None:
    entries = [
        ObservedEnv(name="MAX", type="integer", observed=True),
        ObservedEnv(name="TIMEOUT", type="float", observed=True),
    ]
    values = observe_env(entries, environ={"MAX": "42", "TIMEOUT": "1.5"})
    assert values[0].observed_value == 42
    assert values[1].observed_value == 1.5


def test_assert_allowlisted_rejects_undeclared_names() -> None:
    entries = [_flag()]
    assert_allowlisted(entries, ["FEATURE_ENABLED"])
    with pytest.raises(DescriptorError, match="SOME_OTHER_VAR"):
        assert_allowlisted(entries, ["SOME_OTHER_VAR"])


def test_redact_never_exposes_secret_content() -> None:
    value = ConfiguredValue(
        name="X",
        is_set=True,
        requested_value="hidden",
        configured_value="hidden",
        effective_value="hidden",
        observed_value="hidden",
    )
    payload = value.redacted()
    for field in ("requested_value", "configured_value", "effective_value", "observed_value"):
        assert payload[field] is None
    assert payload["is_set"] is True
