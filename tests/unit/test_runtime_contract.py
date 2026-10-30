"""Runtime contract models: the configuration triad and its trust level."""

from __future__ import annotations

from akbench.runtime.contract import (
    ExecutionMode,
    Lifecycle,
    RuntimeConfigReport,
    RuntimeManager,
    RuntimeState,
    VerificationStatus,
)


def test_manager_protocol_is_runtime_checkable() -> None:
    """Any structurally complete adapter is a runtime manager."""

    class ShapeCheck:
        runtime_id = "r"
        lifecycle = None

        def start(self) -> None: ...
        def stop(self) -> None: ...
        def healthcheck(self) -> bool: return True
        def apply_configuration(self, config: dict) -> None: ...
        def read_configuration(self): return RuntimeConfigReport()
        def verify_configuration(self, expected: dict): return RuntimeConfigReport()
        def collect_runtime_state(self) -> RuntimeState: return RuntimeState()

    assert isinstance(ShapeCheck(), RuntimeManager)


def test_configuration_triad_keeps_the_plan_field_names() -> None:
    report = RuntimeConfigReport(
        requested={"model": "a"},
        effective=None,
        observed={"served_models": ["a", "b"]},
        verification_status=VerificationStatus.UNSUPPORTED,
        notes=["not readable over HTTP"],
    )
    payload = report.as_dict()

    assert set(payload) == {
        "requested_config",
        "effective_config",
        "observed_config",
        "verification_status",
        "notes",
    }
    assert payload["effective_config"] is None
    assert payload["verification_status"] == "unsupported"


def test_unverified_is_the_default_status() -> None:
    """Silence means unverified, never an implied pass (plan section 13)."""
    assert RuntimeConfigReport().verification_status is VerificationStatus.UNVERIFIED
    assert RuntimeConfigReport().effective is None


def test_execution_modes_are_the_declared_three() -> None:
    assert {mode.value for mode in ExecutionMode} == {"direct", "runtime", "router"}


def test_lifecycles_are_external_and_managed() -> None:
    assert {item.value for item in Lifecycle} == {"external", "managed"}


def test_runtime_state_reports_unknowns_as_none() -> None:
    state = RuntimeState()
    payload = state.as_dict()
    assert payload["healthy"] is None
    assert payload["metrics_available"] is None
    assert payload["models"] == []
    assert payload["lifecycle"] is None
