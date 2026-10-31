"""Live contract check: the real Codex CLI through the adapter.

The stub suite proves the adapter's mechanics; this check proves the recipe
still matches the real CLI end to end, which is the phase 4 done criterion. It
is slow and external, so it only runs when explicitly enabled:

    AKBENCH_RUN_LIVE=1 .venv/bin/pytest tests/contract/test_codex_live_contract.py

Requirements are checked, never assumed: the ``codex`` binary on PATH, and the
credential named by the runtime descriptor's ``required_env``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from akbench.agents.codex import CodexAdapter, CodexOptions
from akbench.agents.contract import AgentConfig, RuntimeBinding
from akbench.agents.errors import AgentConfigError
from akbench.descriptors import DescriptorKind, load_descriptor_file

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK = "Create a file named proof.txt containing exactly: akbench phase 4 ok"

live = pytest.mark.live
reason = "live check disabled; set AKBENCH_RUN_LIVE=1 to run it"


def _descriptor(kind: DescriptorKind, descriptor_id: str):
    filename = "llm-router.yaml" if kind is DescriptorKind.RUNTIME else "codex.yaml"
    registry = load_descriptor_file(
        REPO_ROOT / "descriptors" / f"{kind.value}s" / filename,
        kind,
    )
    loaded = registry.get(kind, descriptor_id)
    assert loaded is not None, f"the {descriptor_id} descriptor must exist"
    return loaded.descriptor


def _binding() -> RuntimeBinding:
    runtime = _descriptor(DescriptorKind.RUNTIME, "llm-router")
    required = runtime.runtime.required_env
    return RuntimeBinding(
        runtime_id=runtime.id,
        base_url=runtime.runtime.base_url,
        api_key_env=required[0] if required else None,
    )


def _require_live_host() -> None:
    if os.environ.get("AKBENCH_RUN_LIVE") != "1":
        pytest.skip(reason)
    if shutil.which("codex") is None:
        pytest.skip("the codex CLI is not on PATH")
    binding = _binding()
    if not binding.api_key_env or not os.environ.get(binding.api_key_env):
        pytest.skip(f"credential {binding.api_key_env!r} required by the runtime is not set")


@live
class TestCodexLiveContract:
    """One real run, exercised only through the universal contract."""

    def test_real_cli_runs_through_the_adapter(self, tmp_path: Path) -> None:
        _require_live_host()
        config = AgentConfig(
            agent_id="codex",
            parameters={"sandbox_mode": "workspace-write", "approval_policy": "never"},
            artifacts_dir=tmp_path / "artifacts",
            runtime=_binding(),
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        adapter = CodexAdapter(_descriptor(DescriptorKind.AGENT, "codex"), CodexOptions())
        adapter.validate_environment(config)

        session = adapter.start_session(config, workspace)
        adapter.submit_task(session, TASK)
        result = adapter.wait_for_completion(session, timeout=600)
        result = adapter.close_session(session)

        assert result.session_id, "the real CLI reports its thread id"
        assert result.agent_version, "the real CLI reports its version"
        payload = result.as_dict()
        assert payload["agent_id"] == "codex"
        assert payload["status"] in {status.value for status in result.status.__class__}

        if result.status.value != "completed":
            pytest.skip(
                f"live run ended as {result.status.value}; "
                f"see {result.artifacts.get('stderr', 'no stderr artifact')}"
            )

        proof = workspace / "proof.txt"
        assert proof.is_file(), "the agent was expected to write the requested file"
        assert "akbench phase 4 ok" in proof.read_text(encoding="utf-8")
        assert result.usage is not None and result.usage.input_tokens
        assert result.observations["tool_call_count"] > 0
        assert result.observations["cost"] is None

    def test_missing_credential_is_refused_before_any_work(self, tmp_path: Path) -> None:
        """A live host without its credential must fail validation, not hang."""
        if os.environ.get("AKBENCH_RUN_LIVE") != "1":
            pytest.skip(reason)
        binding = _binding()
        if not binding.api_key_env:
            pytest.skip("the runtime descriptor declares no credential")

        credential = binding.api_key_env
        saved = os.environ.pop(credential, None)
        try:
            config = AgentConfig(
                agent_id="codex",
                artifacts_dir=tmp_path / "artifacts",
                runtime=binding,
            )
            with pytest.raises(AgentConfigError) as excinfo:
                CodexAdapter().validate_environment(config)
            assert credential in str(excinfo.value)
        finally:
            if saved is not None:
                os.environ[credential] = saved
