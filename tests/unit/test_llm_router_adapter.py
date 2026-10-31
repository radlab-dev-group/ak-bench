"""LLM Router adapter against a local HTTP stub.

The stub implements the endpoints the adapter uses, exactly as verified in
``docs/ROUTER_INTEGRATION.md``: ``/health`` answers healthy, ``/v1/models``
lists models, ``/metrics`` is served, and the configuration endpoints are
denied. No network is involved.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from akbench.descriptors.runtime import RuntimeDescriptor
from akbench.runtime import LlmRouterAdapter, LlmRouterOptions
from akbench.runtime.contract import VerificationStatus
from akbench.runtime.errors import CapabilityNotSupported
from akbench.runtime.http import HttpError


class StubHandler(BaseHTTPRequestHandler):
    """A stand-in for the router's HTTP surface (the verified subset)."""

    server_version = "akbench-stub/1.0"
    routes: dict[str, tuple[int, str]]  # set by the fixture before each test

    def do_GET(self) -> None:  # stdlib handler naming
        route = self.routes.get(self.path)
        if route is None:
            self._send(404, json.dumps({"error": "not found"}))
            return
        status, body = route
        self._send(status, body)

    def _send(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # keep the stub quiet
        return None


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> tuple[str, dict[str, tuple[int, str]]]:
    StubHandler.routes = {
        "/health": (200, json.dumps({"body": "healthy", "status": True, "stream": False})),
        "/v1/models": (
            200,
            json.dumps({"data": [{"id": "model-a"}, {"id": "model-b"}]}),
        ),
        "/metrics": (200, "# stub metrics\nllm_router_tokens_total 3\n"),
        "/config": (403, json.dumps({"error": "denied by policy"})),
        "/admin/config": (403, json.dumps({"error": "denied by policy"})),
        "/healthz": (403, json.dumps({"error": "denied by policy"})),
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("SOME_ROUTER_KEY", "test-key-not-logged")
    yield f"http://127.0.0.1:{server.server_address[1]}", StubHandler.routes
    server.shutdown()
    server.server_close()


def descriptor(base_url: str) -> RuntimeDescriptor:
    import yaml

    return RuntimeDescriptor.model_validate(
        yaml.safe_load(
            """
schema_version: "1.0"
id: sample-router
version: "1.0.0"
title: Sample Router
runtime:
  adapter: llm_router
  execution_modes: [direct, runtime, router]
  supported_lifecycles: [managed, external]
  base_url: BASEURL
  healthcheck_path: /health
  metrics_path: /metrics
  required_env: [SOME_ROUTER_KEY]
""".replace("BASEURL", base_url)
        )
    )


def make_adapter(stub_url: str, **overrides: object) -> LlmRouterAdapter:
    from akbench.descriptors.runtime import Lifecycle

    if "lifecycle" in overrides and isinstance(overrides["lifecycle"], str):
        overrides["lifecycle"] = Lifecycle(overrides["lifecycle"])  # type: ignore[assignment]
    return LlmRouterAdapter(
        descriptor(stub_url),
        LlmRouterOptions(base_url=stub_url, **overrides),  # type: ignore[arg-type]
    )


def test_healthcheck_reads_the_verified_shape(stub: tuple[str, dict]) -> None:
    url, _ = stub
    assert make_adapter(url).healthcheck() is True


def test_unhealthy_health_endpoint_is_reported(stub: tuple[str, dict]) -> None:
    url, routes = stub
    routes["/health"] = (503, json.dumps({"error": "down"}))
    assert make_adapter(url).healthcheck() is False


def test_unreachable_host_is_distinguished_from_denied(stub: tuple[str, dict]) -> None:
    adapter = LlmRouterAdapter(None, LlmRouterOptions(base_url="http://127.0.0.1:1"))
    assert adapter.healthcheck() is False
    assert adapter.list_models() is None


def test_model_inventory_is_read(stub: tuple[str, dict]) -> None:
    url, _ = stub
    assert make_adapter(url).list_models() == ["model-a", "model-b"]


def test_model_inventory_survives_an_alias_gap_note(stub: tuple[str, dict]) -> None:
    """The inventory is what the router lists; aliases simply are not there."""
    url, routes = stub
    routes["/v1/models"] = (200, json.dumps({"data": []}))
    assert make_adapter(url).list_models() == []


def test_metrics_availability_is_observed(stub: tuple[str, dict]) -> None:
    url, routes = stub
    state = make_adapter(url).collect_runtime_state()
    assert state.metrics_available is True
    assert state.healthy is True
    assert state.models == ["model-a", "model-b"]

    routes["/metrics"] = (404, json.dumps({"error": "gone"}))
    assert make_adapter(url).collect_runtime_state().metrics_available is False


def test_effective_configuration_is_unsupported_over_http(stub: tuple[str, dict]) -> None:
    url, _ = stub
    report = make_adapter(url).read_configuration()
    assert report.verification_status is VerificationStatus.UNSUPPORTED
    assert report.effective is None
    assert "served_models" in report.observed
    assert any("not readable over HTTP" in note for note in report.notes)


def test_configuration_is_verified_from_a_host_file(stub: tuple[str, dict], tmp_path: Path) -> None:
    url, _ = stub
    config_file = tmp_path / "models-config.json"
    config_file.write_text(json.dumps({"active_models": ["model-a"]}), encoding="utf-8")
    adapter = make_adapter(url, config_file=config_file)

    report = adapter.read_configuration()

    assert report.verification_status is VerificationStatus.VERIFIED
    assert report.effective == {"active_models": ["model-a"]}
    assert report.observed["config_file"] == str(config_file)


def test_verification_flags_mismatches(stub: tuple[str, dict], tmp_path: Path) -> None:
    url, _ = stub
    config_file = tmp_path / "models-config.json"
    config_file.write_text(json.dumps({"active_models": ["model-a"]}), encoding="utf-8")
    adapter = make_adapter(url, config_file=config_file)

    match = adapter.verify_configuration({"active_models": ["model-a"]})
    assert match.verification_status is VerificationStatus.VERIFIED
    assert match.observed.get("mismatches") is None

    mismatch = adapter.verify_configuration({"active_models": ["model-x"]})
    assert mismatch.verification_status is VerificationStatus.UNVERIFIED
    assert "active_models" in mismatch.observed["mismatches"]


def test_verification_without_readable_config_is_unverified(stub: tuple[str, dict]) -> None:
    url, _ = stub
    report = make_adapter(url).verify_configuration({"active_models": ["model-a"]})
    assert report.verification_status is VerificationStatus.UNSUPPORTED
    assert report.effective is None


def test_apply_configuration_is_refused(stub: tuple[str, dict]) -> None:
    url, _ = stub
    with pytest.raises(CapabilityNotSupported, match="no configuration write endpoint"):
        make_adapter(url).apply_configuration({"active_models": ["model-a"]})


def test_external_runtime_is_never_started(stub: tuple[str, dict]) -> None:
    url, _ = stub
    with pytest.raises(CapabilityNotSupported, match="lifecycle=external"):
        make_adapter(url).start()
    # stopping something that was never started is a harmless no-op
    make_adapter(url).stop()


def test_managed_runtime_without_a_command_is_unusable(stub: tuple[str, dict]) -> None:
    url, _ = stub
    adapter = make_adapter(url, lifecycle="managed")
    with pytest.raises(CapabilityNotSupported, match="declares no start command"):
        adapter.start()


def test_managed_runtime_start_and_stop(tmp_path: Path) -> None:
    """A managed instance is started with the configured command and health-checked."""
    log = tmp_path / "router.log"
    command = [
        "/bin/sh",
        "-c",
        f"touch {log} && sleep 5",
    ]
    from akbench.descriptors.runtime import Lifecycle

    adapter = LlmRouterAdapter(
        None,
        LlmRouterOptions(
            base_url="http://127.0.0.1:1",
            lifecycle=Lifecycle.MANAGED,
            start_command=command,
            ready_timeout=1.0,
        ),
    )
    with pytest.raises(Exception, match="did not become healthy"):
        adapter.start()
    # the process must have been reaped even when readiness never arrived
    assert log.is_file()


def test_http_errors_are_reported_not_raised(stub: tuple[str, dict]) -> None:
    from akbench.runtime.http import get_json

    url, _ = stub
    response = get_json(f"{url}/config")
    assert response.status == 403
    assert response.ok is False
    with pytest.raises(HttpError):
        get_json("http://127.0.0.1:1/nope", timeout=1.0)
