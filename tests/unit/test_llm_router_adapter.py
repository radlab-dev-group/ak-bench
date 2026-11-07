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

from akbench.descriptors.runtime import Lifecycle, RuntimeDescriptor
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


def test_descriptor_launch_block_fills_the_adapter_options(stub: tuple[str, dict]) -> None:
    """A ``managed`` block in the descriptor is what makes a runtime startable."""
    import yaml

    url, _ = stub
    body = yaml.safe_load(
        """
schema_version: "1.0"
id: managed-router
version: "1.0.0"
runtime:
  adapter: llm_router
  execution_modes: [router, runtime, direct]
  supported_lifecycles: [managed]
  base_url: BASEURL
  managed:
    command: ["/bin/sh", "-c", "true"]
    cwd: /srv/router
    env:
      LLM_ROUTER_AUTH_ENABLED: "false"
    factor_env:
      knowledge_enabled: LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED
    config_file: resources/configs/models-config.json
    ready_timeout: 42.0
    stop_grace: 21.0
    log_file: router.log
""".replace("BASEURL", url)
    )
    descriptor = RuntimeDescriptor.model_validate(body)
    adapter = LlmRouterAdapter(descriptor)

    assert adapter.lifecycle is Lifecycle.MANAGED
    assert adapter.options.start_command == ["/bin/sh", "-c", "true"]
    assert adapter.options.cwd == Path("/srv/router")
    assert adapter.options.env == {"LLM_ROUTER_AUTH_ENABLED": "false"}
    assert adapter.options.factor_env == {
        "knowledge_enabled": "LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED"
    }
    assert adapter.options.config_file == Path("resources/configs/models-config.json")
    assert adapter.options.ready_timeout == 42.0
    assert adapter.options.stop_grace == 21.0
    assert adapter.options.log_file == Path("router.log")


def test_runtime_accepting_both_lifecycles_stays_external(stub: tuple[str, dict]) -> None:
    """A descriptor that also accepts ``external`` is never started unasked."""
    import yaml

    url, _ = stub
    body = yaml.safe_load(
        """
schema_version: "1.0"
id: shared-router
version: "1.0.0"
runtime:
  adapter: llm_router
  supported_lifecycles: [managed, external]
  base_url: BASEURL
  managed:
    command: ["/bin/sh", "-c", "true"]
""".replace("BASEURL", url)
    )
    adapter = LlmRouterAdapter(RuntimeDescriptor.model_validate(body))
    assert adapter.lifecycle is Lifecycle.EXTERNAL
    with pytest.raises(CapabilityNotSupported, match="lifecycle=external"):
        adapter.start()


def test_launch_environment_carries_descriptor_env_and_run_factors(
    stub: tuple[str, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, _ = stub
    monkeypatch.setenv("LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED", "stale-shell-value")
    adapter = make_adapter(
        url,
        lifecycle="managed",
        start_command=["/bin/sh", "-c", "true"],
        env={"LLM_ROUTER_AUTH_ENABLED": "false"},
        factor_env={"knowledge_enabled": "LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED"},
        factor_values={"knowledge_enabled": False},
    )
    environment = adapter.process_environment()
    # the variant value beats both the descriptor's env and the ambient shell
    assert environment["LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED"] == "false"
    assert environment["LLM_ROUTER_AUTH_ENABLED"] == "false"
    assert "SOME_ROUTER_KEY" in environment  # the ambient environment survives


def test_a_declared_secret_reaches_the_process_and_is_masked_only_in_the_record(
    stub: tuple[str, dict],
) -> None:
    """Masking belongs to the record, never to the process being launched.

    The launch environment and the run record are built from the same declared
    values, so a mask applied to both would start the router with `***` where a
    password belongs: the instance would come up healthy, the plugin would try
    to use the credential, and the failure would show up as a downstream 400
    the report has no way to explain.
    """
    url, _ = stub
    adapter = make_adapter(
        url,
        lifecycle="managed",
        start_command=["/bin/sh", "-c", "true"],
        env={"LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_PASSWORD": "the-real-secret"},
    )

    assert adapter.process_environment()["LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_PASSWORD"] == (
        "the-real-secret"
    )
    assert adapter.declared_environment()["LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_PASSWORD"] == "***"


def test_a_managed_instance_refuses_a_port_a_foreign_process_already_serves(
    stub: tuple[str, dict],
) -> None:
    """A readiness answer from a process the run did not start is a refusal.

    A leftover router on the configured port would answer /health for a run
    that never bound it, so the run would measure an instance it does not own
    and keep a log that proves nothing. The start must fail instead of the
    task being allowed to begin.
    """
    url, _ = stub
    adapter = LlmRouterAdapter(
        None,
        LlmRouterOptions(
            base_url=url,
            lifecycle=Lifecycle.MANAGED,
            start_command=["/bin/sh", "-c", "true"],
        ),
    )
    with pytest.raises(Exception, match="already answered by a process this run did not start"):
        adapter.start()
    # and nothing was started, so there is nothing to stop
    adapter.stop()


def test_a_managed_instance_reports_a_child_that_dies_before_readiness(
    stub: tuple[str, dict], tmp_path: Path
) -> None:
    """A child that cannot bind its port must fail the run, not hide behind it."""
    log_file = tmp_path / "router.log"
    adapter = LlmRouterAdapter(
        None,
        LlmRouterOptions(
            base_url="http://127.0.0.1:1",
            lifecycle=Lifecycle.MANAGED,
            start_command=["/bin/sh", "-c", "exit 7"],
            ready_timeout=5.0,
            log_file=log_file,
        ),
    )
    with pytest.raises(Exception, match="exited with code 7 before becoming healthy"):
        adapter.start()
    assert adapter.log_path == log_file


def test_http_errors_are_reported_not_raised(stub: tuple[str, dict]) -> None:
    from akbench.runtime.http import get_json

    url, _ = stub
    response = get_json(f"{url}/config")
    assert response.status == 403
    assert response.ok is False
    with pytest.raises(HttpError):
        get_json("http://127.0.0.1:1/nope", timeout=1.0)


def test_log_dir_override_places_the_descriptor_log_in_the_run(
    stub: tuple[str, dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A descriptor names the log; the run decides the directory it lands in.

    The descriptor keeps a relative name, so without the run's directory the
    launched process would write into whatever directory the CLI happened to be
    started from, and the run would keep no evidence.
    """
    import yaml

    monkeypatch.chdir(tmp_path)
    body = yaml.safe_load(
        """
schema_version: "1.0"
id: logging-router
version: "1.0.0"
runtime:
  adapter: llm_router
  supported_lifecycles: [managed]
  base_url: BASEURL
  managed:
    command: ["/bin/sh", "-c", "echo written-into-the-run-log"]
    log_file: router.log
""".replace("BASEURL", "http://127.0.0.1:1")
    )
    adapter = LlmRouterAdapter(
        RuntimeDescriptor.model_validate(body), log_dir=tmp_path / "artifacts" / "runs" / "one"
    )
    with pytest.raises(Exception, match="before becoming healthy"):
        adapter.start()

    written = tmp_path / "artifacts" / "runs" / "one" / "router.log"
    assert adapter.log_path == written
    assert "written-into-the-run-log" in written.read_text(encoding="utf-8")
    assert not (tmp_path / "router.log").exists()


def test_a_process_that_dies_says_so_with_its_log(
    stub: tuple[str, dict], tmp_path: Path
) -> None:
    """An instance that exits during startup must report the code and the log.

    Waiting out the readiness timeout and quoting it would describe a wait, not
    the crash, and leave the user looking for a slow start.
    """
    _url, routes = stub
    routes["/health"] = (503, json.dumps({"body": "unhealthy"}))
    adapter = LlmRouterAdapter(
        None,
        LlmRouterOptions(
            base_url="http://127.0.0.1:1",
            lifecycle=Lifecycle.MANAGED,
            start_command=["/bin/sh", "-c", "echo boom; exit 3"],
            log_file=tmp_path / "router.log",
            ready_timeout=30.0,
        ),
    )
    with pytest.raises(Exception, match=r"exited with code 3.*router\.log"):
        adapter.start()


def test_the_run_environment_beats_the_descriptor_defaults(
    stub: tuple[str, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A variant's runtime_env is the last word on the process environment.

    A pipeline that sits in the descriptor's static environment would load its
    plugins in every run of that runtime; the variant that wants a different
    pipeline has to be able to win over it.
    """
    url, _ = stub
    monkeypatch.setenv("STALE_PIPELINE", "from-the-shell")
    adapter = LlmRouterAdapter(
        None,
        LlmRouterOptions(
            base_url=url,
            lifecycle=Lifecycle.MANAGED,
            start_command=["/bin/sh", "-c", "true"],
            env={"STALE_PIPELINE": "from-the-descriptor", "KEPT": "yes"},
            factor_env={"a": "FACTOR_VAR"},
            factor_values={"a": True},
            runtime_env={"STALE_PIPELINE": "from-the-variant", "RUN_ONLY": "1"},
        ),
    )
    environment = adapter.process_environment()

    assert environment["STALE_PIPELINE"] == "from-the-variant"
    assert environment["FACTOR_VAR"] == "true"
    assert environment["RUN_ONLY"] == "1"
    assert environment["KEPT"] == "yes"
    # the ambient environment is still there, under everything the run declared
    assert "SOME_ROUTER_KEY" in environment


def test_declared_environment_reports_what_the_run_set_and_masks_secrets(
    stub: tuple[str, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record keeps the run's declared environment, never the operator's.

    The ambient environment carries the operator's credentials and must not
    reach the run record; a declared value whose name marks it as a secret is
    reported by name only.
    """
    url, _ = stub
    monkeypatch.setenv("AMBIENT_TOKEN", "should-not-be-recorded")
    adapter = LlmRouterAdapter(
        None,
        LlmRouterOptions(
            base_url=url,
            lifecycle=Lifecycle.MANAGED,
            start_command=["/bin/sh", "-c", "true"],
            env={"SSE_API_PASSWORD": "hunter2", "PIPELINE": "routing,knowledge"},
            factor_env={"a": "FACTOR_VAR"},
            factor_values={"a": True},
            runtime_env={"PIPELINE": "routing"},
        ),
    )

    declared = adapter.declared_environment()

    assert "AMBIENT_TOKEN" not in declared
    assert declared["SSE_API_PASSWORD"] == "***"
    assert declared["PIPELINE"] == "routing"
    assert declared["FACTOR_VAR"] == "true"


# ------------------------------------------------------- per-request evidence

ROUTER_LOG = "\n".join(
    [
        "2026-11-03 17:33:51,347 INFO llm_router_api.endpoints.endpoint_i: "
        "Overriding trigger model: auto_codex",
        "2026-11-03 17:34:23,469 INFO llm_router_api.endpoints.endpoint_i: "
        "Codex routing: mode=test source=heuristic model=qwen/Qwen3.8-27B similarity=0.917",
        "2026-11-03 17:34:23,503 DEBUG llm_router_api.endpoints.endpoint_i: "
        "Request model qwen/Qwen3.8-27B with config id: qwen3.8:27b-66:7000",
        "2026-11-03 17:34:44,410 DEBUG llm_router_api.endpoints.endpoint_i: "
        "Request model qwen/Qwen3.8-Flash-Next with config id: flash-66:7000",
    ]
)


def _managed_adapter_with_log(tmp_path: Path, url: str) -> LlmRouterAdapter:
    log_file = tmp_path / "router.log"
    log_file.write_text(ROUTER_LOG, encoding="utf-8")
    adapter = make_adapter(url, lifecycle="managed")
    adapter.log_path = log_file
    return adapter


def test_model_evidence_names_the_models_the_instance_served(
    stub: tuple[str, dict], tmp_path: Path
) -> None:
    """The log of a process this run started says which model served requests."""
    url, _ = stub
    evidence = _managed_adapter_with_log(tmp_path, url).model_request_evidence()

    assert evidence["available"] is True
    assert evidence["log"] == "router.log"
    assert evidence["served_models"] == ["qwen/Qwen3.8-27B", "qwen/Qwen3.8-Flash-Next"]
    assert evidence["routing_decisions"] == ["qwen/Qwen3.8-27B"]
    assert evidence["received_models"] == ["auto_codex"]


def test_model_evidence_is_not_attributable_to_an_external_instance(
    stub: tuple[str, dict], tmp_path: Path
) -> None:
    """A shared router's log is not this run's evidence, so there is none."""
    url, _ = stub
    adapter = make_adapter(url)  # lifecycle=external
    adapter.log_path = tmp_path / "router.log"

    evidence = adapter.model_request_evidence()
    assert evidence["available"] is False
    assert "cannot be attributed" in evidence["note"]


def test_model_evidence_without_a_log_is_honest_about_being_absent(
    stub: tuple[str, dict], tmp_path: Path
) -> None:
    url, _ = stub
    adapter = make_adapter(url, lifecycle="managed")
    adapter.log_path = tmp_path / "never-written.log"

    evidence = adapter.model_request_evidence()
    assert evidence["available"] is False
    assert "log" in evidence["note"]


def test_model_evidence_of_a_run_with_no_requests_is_empty(tmp_path: Path) -> None:
    """An empty log is evidence that nothing was served, not a missing reading."""
    url = "http://127.0.0.1:1"
    adapter = _managed_adapter_with_log(tmp_path, url)
    adapter.log_path.write_text("booting\n", encoding="utf-8")

    evidence = adapter.model_request_evidence()
    assert evidence["available"] is True
    assert evidence["served_models"] == []
