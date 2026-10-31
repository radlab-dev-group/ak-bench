"""Plugin adapters (plan section 10): honest state, verification, metrics.

The rules under test are the ones that keep a benchmark report trustworthy:
only declared variables are observed, a secret is presence only, verification
needs evidence, and a plugin metric without a source stays unavailable.
"""

from __future__ import annotations

import pytest

from akbench.descriptors.plugin import PluginDescriptor
from akbench.descriptors.statuses import VerificationStatus
from akbench.plugins import build_plugin_registry
from akbench.plugins.adapter import NO_PLUGIN_METRICS, LlmRouterPluginAdapter
from akbench.plugins.contract import PluginAdapterError

TOGGLE = "AKBENCH_TEST_ENABLED"
TOGGLE_ENTRY = {
    "name": TOGGLE,
    "type": "boolean",
    "role": "feature_toggle",
    "observed": True,
    "dimension": True,
    "controllable": True,
}
TOKEN_ENTRY = {
    "name": "AKBENCH_TEST_TOKEN",
    "type": "string",
    "role": "secret",
    "observed": True,
}


def _descriptor(**benchmark: object) -> PluginDescriptor:
    body: dict[str, object] = {
        "schema_version": "1.0",
        "id": "test_plugin",
        "version": "1.0.0",
        "title": "Test plugin",
        "plugin": {"provider": "llm-router", "type": "knowledge", "capabilities": ["retrieval"]},
        "benchmark": {
            "enabled": True,
            "enabled_when": TOGGLE,
            "observed_env": [TOGGLE_ENTRY, TOKEN_ENTRY],
            "metrics": ["knowledge_write_count"],
            "verification": {"required": True, "methods": ["effective_router_config"]},
        },
    }
    body["benchmark"] = {**body["benchmark"], **benchmark}  # type: ignore[arg-type]
    return PluginDescriptor.model_validate(body)


def test_enabled_when_must_name_an_allowlisted_entry() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        _descriptor(enabled_when="NOT_DECLARED")


def test_observe_reads_only_the_declared_allowlist() -> None:
    adapter = LlmRouterPluginAdapter()
    state = adapter.observe(
        _descriptor(),
        environ={TOGGLE: "1", "AKBENCH_UNDECLARED": "peek"},
    )

    assert {value.name for value in state.values} == {TOGGLE, "AKBENCH_TEST_TOKEN"}
    assert state.value(TOGGLE) is not None
    assert state.value(TOGGLE).observed_value is True
    assert state.verification_status is VerificationStatus.UNVERIFIED


def test_a_requested_value_outside_the_allowlist_is_refused() -> None:
    adapter = LlmRouterPluginAdapter()
    with pytest.raises(PluginAdapterError, match="not allowlisted"):
        adapter.observe(_descriptor(), requested={"AKBENCH_SMUGGLED": "1"})


def test_secret_presence_is_recorded_and_value_never_read() -> None:
    adapter = LlmRouterPluginAdapter()
    state = adapter.observe(_descriptor(), environ={"AKBENCH_TEST_TOKEN": "hunter2"})

    secret = state.value("AKBENCH_TEST_TOKEN")
    assert secret is not None
    assert secret.is_set is True
    assert secret.observed_value is None
    assert "hunter2" not in str(state.model_dump())


def test_enabled_comes_from_the_toggle_the_descriptor_names() -> None:
    adapter = LlmRouterPluginAdapter()
    assert adapter.observe(_descriptor(), environ={TOGGLE: "true"}).enabled is True
    assert adapter.observe(_descriptor(), environ={TOGGLE: "false"}).enabled is False

    unset = adapter.observe(_descriptor(), environ={})
    assert unset.enabled is False
    assert "not set" in (unset.note or "")


def test_a_plugin_without_a_toggle_reports_activation_as_unobservable() -> None:
    descriptor = _descriptor(enabled_when=None)
    state = LlmRouterPluginAdapter().observe(descriptor, environ={TOGGLE: "true"})

    assert state.enabled is False
    assert "enabled_when" in (state.note or "")


def test_verification_without_evidence_is_unsupported_not_presumed() -> None:
    adapter = LlmRouterPluginAdapter()
    state = adapter.verify(_descriptor(), adapter.observe(_descriptor(), environ={TOGGLE: "1"}))

    assert state.verification_status is VerificationStatus.UNSUPPORTED
    assert "effective_router_config" in (state.note or "")


def test_verification_against_an_effective_configuration() -> None:
    adapter = LlmRouterPluginAdapter(config_reader=lambda: {TOGGLE: True})
    observed = adapter.observe(_descriptor(), requested={TOGGLE: True}, environ={TOGGLE: "true"})
    state = adapter.verify(_descriptor(), observed)

    assert state.verification_status is VerificationStatus.VERIFIED
    assert state.value(TOGGLE).effective_value is True


def test_a_requested_value_that_does_not_hold_is_a_mismatch() -> None:
    adapter = LlmRouterPluginAdapter(config_reader=lambda: {TOGGLE: False})
    observed = adapter.observe(_descriptor(), requested={TOGGLE: True}, environ={TOGGLE: "0"})
    state = adapter.verify(_descriptor(), observed)

    assert state.verification_status is VerificationStatus.MISMATCH
    assert "mismatch" in (state.note or "")


def test_an_effective_secret_is_never_copied_into_the_state() -> None:
    adapter = LlmRouterPluginAdapter(config_reader=lambda: {"AKBENCH_TEST_TOKEN": "leaked"})
    state = adapter.verify(_descriptor(), adapter.observe(_descriptor()))

    secret = state.value("AKBENCH_TEST_TOKEN")
    assert secret.effective_value is None
    assert "leaked" not in str(state.model_dump())


def test_a_reader_that_raises_is_absent_evidence() -> None:
    def broken() -> None:
        raise OSError("cannot read")

    state = LlmRouterPluginAdapter(config_reader=broken).verify(
        _descriptor(), LlmRouterPluginAdapter().observe(_descriptor())
    )
    assert state.verification_status is VerificationStatus.UNSUPPORTED


def test_plugin_metrics_stay_unavailable_without_a_source() -> None:
    adapter = LlmRouterPluginAdapter()
    state = adapter.observe(_descriptor(), environ={})
    metrics = adapter.normalize_metrics(_descriptor(), state)

    assert [metric.name for metric in metrics] == ["knowledge_write_count"]
    assert metrics[0].available is False
    assert metrics[0].value is None
    assert metrics[0].reason == NO_PLUGIN_METRICS


def test_an_injected_metric_source_makes_a_metric_measured() -> None:
    adapter = LlmRouterPluginAdapter(metric_source={"knowledge_write_count": 7})
    metrics = adapter.normalize_metrics(_descriptor(), adapter.observe(_descriptor()))

    assert metrics[0].available is True
    assert metrics[0].value == 7


def test_report_combines_observation_verification_and_metrics() -> None:
    report = LlmRouterPluginAdapter().report(
        _descriptor(), digest="sha256:abc", environ={TOGGLE: "1"}
    )

    assert report.plugin_id == "test_plugin"
    assert report.enabled is True
    assert report.digest == "sha256:abc"
    assert report.state is not None
    assert report.metrics and not report.metrics[0].available


def test_registry_selects_adapters_by_provider() -> None:
    descriptor = _descriptor()
    registry = build_plugin_registry([descriptor])

    assert registry.supports(descriptor)
    assert registry.resolve(descriptor).adapter_id == "llm_router_plugin"


def test_an_unsupported_provider_is_reported_not_silently_dropped() -> None:
    descriptor = _descriptor()
    descriptor.plugin.provider = "some-other-host"
    registry = build_plugin_registry()

    reports = registry.reports([descriptor])
    assert len(reports) == 1
    assert "no adapter handles provider" in reports[0].note
    with pytest.raises(PluginAdapterError, match="no adapter handles provider"):
        registry.resolve(descriptor)


def test_requested_configuration_for_an_unknown_plugin_is_an_error() -> None:
    registry = build_plugin_registry([_descriptor()])
    with pytest.raises(PluginAdapterError, match="not passed"):
        registry.reports([], requested={"other_plugin": {TOGGLE: True}})


def test_evidence_for_an_unregistered_plugin_is_an_error() -> None:
    with pytest.raises(PluginAdapterError, match="not registered"):
        build_plugin_registry([], metric_sources={"ghost": {"knowledge_write_count": 1}})
