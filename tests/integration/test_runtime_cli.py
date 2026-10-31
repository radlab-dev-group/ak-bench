"""CLI behaviour of the runtime command group, against a local HTTP stub.

The temp project's runtime descriptor is rewritten to point at a stub server,
so the CLI is driven exactly as in production: registry, descriptor, adapter,
HTTP. Nothing internal is monkeypatched, and no network is used.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from typer.testing import CliRunner

from akbench.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


class StubHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, str]]

    def do_GET(self) -> None:  # stdlib handler naming
        route = self.routes.get(self.path)
        status, body = (404, json.dumps({"error": "not found"})) if route is None else route
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # keep the stub quiet
        return None


STUB_ROUTES = {
    "/health": (200, json.dumps({"body": "healthy", "status": True, "stream": False})),
    "/v1/models": (200, json.dumps({"data": [{"id": "model-a"}]})),
    "/metrics": (200, "# stub metrics\n"),
    "/config": (403, json.dumps({"error": "denied by policy"})),
    "/admin/config": (403, json.dumps({"error": "denied by policy"})),
}


@pytest.fixture
def stub_server() -> Iterator[str]:
    """A local stand-in for the router; yields its base URL."""
    StubHandler.routes = dict(STUB_ROUTES)
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stub_server: str
) -> tuple[Path, str]:
    """A project whose llm-router descriptor points at the local stub."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    shutil.copytree(REPO_ROOT / "descriptors", root / "descriptors")
    url = stub_server

    descriptor = root / "descriptors" / "runtimes" / "llm-router.yaml"
    text = descriptor.read_text(encoding="utf-8")
    descriptor.write_text(
        text.replace("http://192.168.100.65:8081", url),
        encoding="utf-8",
    )

    monkeypatch.setenv("AKBENCH_HOME", str(root))
    for name in list(os.environ):
        if name.startswith("AKBENCH__") or name == "AKBENCH_CONFIG":
            monkeypatch.delenv(name, raising=False)
    return root, url


def _payload(output: str) -> dict:
    return json.loads(output[output.index("{") :])


def test_runtime_list_shows_the_router(project: tuple[Path, str]) -> None:
    result = runner.invoke(app, ["runtime", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["count"] == 1
    assert payload["runtimes"][0]["id"] == "llm-router"
    assert payload["runtimes"][0]["base_url"] == project[1]


def test_runtime_health_reports_healthy(project: tuple[Path, str]) -> None:
    result = runner.invoke(app, ["runtime", "health", "llm-router", "--json"])
    assert result.exit_code == 0, result.output
    assert _payload(result.output)["healthy"] is True


def test_runtime_models_lists_served_models(project: tuple[Path, str]) -> None:
    result = runner.invoke(app, ["runtime", "models", "llm-router", "--json"])
    assert result.exit_code == 0, result.output
    assert _payload(result.output)["models"] == ["model-a"]


def test_runtime_config_reports_unsupported_with_a_reason(project: tuple[Path, str]) -> None:
    result = runner.invoke(app, ["runtime", "config", "llm-router", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["verification_status"] == "unsupported"
    assert payload["effective_config"] is None
    assert any("not readable over HTTP" in note for note in payload["notes"])


def test_runtime_state_snapshots_health_models_metrics(project: tuple[Path, str]) -> None:
    result = runner.invoke(app, ["runtime", "state", "llm-router", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["healthy"] is True
    assert payload["models"] == ["model-a"]
    assert payload["metrics_available"] is True


def test_runtime_health_of_an_unknown_runtime_fails(project: tuple[Path, str]) -> None:
    result = runner.invoke(app, ["runtime", "health", "does-not-exist", "--json"])
    assert result.exit_code == 1
    assert "cannot resolve runtime" in result.output


def test_agent_run_reports_the_execution_plan(
    project: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    shutil.copytree(REPO_ROOT / "datasets", root / "datasets")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "codex"
    shutil.copyfile(REPO_ROOT / "tests" / "contract" / "stubs" / "codex_stub.py", stub)
    stub.chmod(stub.stat().st_mode | 0o111)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ["PATH"]]))

    workspace = tmp_path / "ws"
    workspace.mkdir()
    task_file = tmp_path / "task.txt"
    task_file.write_text("Fix it.", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "agent",
            "run",
            "codex",
            "--task-file",
            str(task_file),
            "--workspace",
            str(workspace),
            "--runtime",
            "llm-router",
            "--mode",
            "router",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["status"] == "completed"
    assert payload["execution"]["mode"] == "router"
    assert payload["execution"]["runtime"] == "llm-router@1.0.0"
    assert payload["execution"]["mode_declared"] is True


def test_agent_run_direct_mode_names_no_runtime(
    project: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "codex"
    shutil.copyfile(REPO_ROOT / "tests" / "contract" / "stubs" / "codex_stub.py", stub)
    stub.chmod(stub.stat().st_mode | 0o111)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ["PATH"]]))

    workspace = tmp_path / "ws"
    workspace.mkdir()
    task_file = tmp_path / "task.txt"
    task_file.write_text("Fix it.", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "agent",
            "run",
            "codex",
            "--task-file",
            str(task_file),
            "--workspace",
            str(workspace),
            "--mode",
            "direct",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result.output)
    assert payload["execution"]["mode"] == "direct"
    assert payload["execution"]["runtime"] is None
