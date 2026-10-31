"""The run orchestrator, end to end, through the generic contracts only.

The subjects are stub CLIs (a fixer, a no-op, a hanger, a failure, an
infrastructure failure). The orchestrator treats them all the same: resolve the
agent from the registry, open a session, submit the task, wait, evaluate and
report. That uniformity is the point of phase 7 — no test, and no line of the
orchestrator, knows what a real agent is.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from akbench.agents.catalog import build_agent_registry
from akbench.agents.codex import CodexAdapter, CodexOptions
from akbench.datasets import Dataset, RepositoryManager, WorkspaceManager
from akbench.descriptors import DescriptorKind, load_descriptor_file
from akbench.evaluators.registry import default_registry
from akbench.orchestration import OrchestrationConfig, RunOrchestrator, RunState
from akbench.orchestration.lifecycle import FORWARD_CHAIN, TERMINAL_STATES, transition_allowed

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_STUB = REPO_ROOT / "tests" / "contract" / "stubs" / "codex_stub.py"
FIXER_STUB = REPO_ROOT / "tests" / "contract" / "stubs" / "codex_fixer_stub.py"


def descriptor():
    registry = load_descriptor_file(
        REPO_ROOT / "descriptors" / "agents" / "codex.yaml",
        DescriptorKind.AGENT,
    )
    loaded = registry.get(DescriptorKind.AGENT, "codex")
    assert loaded is not None
    return loaded.descriptor


STUB_TEMPLATE = '''#!/usr/bin/env python3
"""A throwaway CLI stub with fixed behaviour: no JSON stream, non-zero exit."""
import json
import os
import sys

VERSION = {version!r}
STDERR = {stderr!r}
EXIT_CODE = {code}


def main() -> int:
    if "--version" in sys.argv:
        print(VERSION)
        return 0
    print(STDERR, file=sys.stderr)
    log = os.environ.get("STUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({{"argv": sys.argv, "cwd": os.getcwd()}}) + "\\n")
    return EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
'''


def script_stub(path: Path, *, version: str, stderr: str, code: int) -> str:
    """Write a fixed-behaviour stub CLI and make it executable."""
    template = STUB_TEMPLATE.format(version=version, stderr=stderr, code=code)
    path.write_text(template, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return str(path)


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("STUB_LOG", str(tmp_path / "stub_invocations.jsonl"))

    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    loaded = dataset.require("wordcount-001")
    repos = RepositoryManager(tmp_path / "repos")
    workspaces = WorkspaceManager(repos, tmp_path / "workspaces")

    agent_registry = build_agent_registry([descriptor()])
    harness = {
        "loaded": loaded,
        "workspaces": workspaces,
        "agent_registry": agent_registry,
        "orchestrator": RunOrchestrator(
            agents=agent_registry,
            workspaces=workspaces,
            evaluators=default_registry(),
        ),
        "bin": bin_dir,
        "tmp": tmp_path,
    }
    return harness


def use_stub(harness: dict, binary: str, behaviour: str = "complete") -> None:
    """Point the registered agent at ``binary`` with the given stub behaviour."""
    harness["agent_registry"].register(
        descriptor(),
        lambda spec: CodexAdapter(
            spec,
            CodexOptions(
                binary=binary,
                extra_args=("--stub-behaviour", behaviour),
                interrupt_grace=2.0,
                terminate_grace=1.0,
            ),
        ),
    )


def copy_stub(harness: dict, name: str, source: Path) -> str:
    target = harness["bin"] / name
    shutil.copyfile(source, target)
    target.chmod(target.stat().st_mode | 0o111)
    return str(target)


def config(harness: dict, **overrides) -> OrchestrationConfig:
    values = {
        "task": harness["loaded"],
        "agent_id": "codex",
        "mode": "direct",
        "artifacts_dir": harness["tmp"] / "artifacts",
        "evaluation_dir": harness["tmp"] / "evaluations",
        "task_text": "Repair the word counting defect described in the task.",
        "agent_timeout": 60,
        "evaluation_timeout": 120,
        "apply_mutation": True,
    }
    values.update(overrides)
    return OrchestrationConfig(**values)


def invocations(harness: dict) -> int:
    log = harness["tmp"] / "stub_invocations.jsonl"
    if not log.is_file():
        return 0
    return sum(1 for line in log.read_text(encoding="utf-8").splitlines() if line.strip())


def test_a_fixing_agent_produces_a_passed_run(harness: dict) -> None:
    use_stub(harness, copy_stub(harness, "codex-fixer", FIXER_STUB))

    outcome = harness["orchestrator"].run(config(harness))

    assert outcome.state is RunState.COMPLETED
    assert outcome.ok is True
    assert outcome.detail == "evaluation passed"


def test_an_agent_that_does_nothing_completes_without_passing(harness: dict) -> None:
    use_stub(harness, copy_stub(harness, "codex-noop", CODEX_STUB))

    outcome = harness["orchestrator"].run(config(harness))

    assert outcome.state is RunState.COMPLETED
    assert outcome.ok is False
    assert outcome.detail in {"evaluation partial", "evaluation failed"}


def test_agent_timeout_is_a_timeout_not_a_failure(harness: dict) -> None:
    use_stub(harness, copy_stub(harness, "codex-hang", CODEX_STUB), behaviour="hang")

    outcome = harness["orchestrator"].run(config(harness, agent_timeout=1.0))

    assert outcome.state is RunState.TIMEOUT
    assert outcome.ok is False
    assert invocations(harness) == 1, "a timeout is an agent outcome, never retried"


def test_agent_failure_is_never_retried(harness: dict) -> None:
    binary = script_stub(
        harness["bin"] / "codex-fail",
        version="codex-cli 0.0.0-fail",
        stderr="stub reported a failure",
        code=1,
    )
    use_stub(harness, binary)

    outcome = harness["orchestrator"].run(config(harness, infrastructure_retries=3))

    assert outcome.state is RunState.FAILED
    assert outcome.ok is False
    assert invocations(harness) == 1


def test_infrastructure_failure_is_retried_only_when_configured(harness: dict) -> None:
    binary = script_stub(
        harness["bin"] / "codex-infra",
        version="codex-cli 0.0.0-infra",
        stderr="ERROR: connection refused",
        code=1,
    )
    use_stub(harness, binary)

    outcome = harness["orchestrator"].run(config(harness, infrastructure_retries=1))

    assert outcome.state is RunState.INFRASTRUCTURE_ERROR
    assert invocations(harness) == 2, "one attempt plus one configured retry"


def test_infrastructure_failure_without_a_budget_is_not_retried(harness: dict) -> None:
    binary = script_stub(
        harness["bin"] / "codex-infra2",
        version="codex-cli 0.0.0-infra",
        stderr="ERROR: connection refused",
        code=1,
    )
    use_stub(harness, binary)

    outcome = harness["orchestrator"].run(config(harness))

    assert outcome.state is RunState.INFRASTRUCTURE_ERROR
    assert invocations(harness) == 1


def test_invalid_configuration_has_its_own_state(harness: dict) -> None:
    use_stub(harness, copy_stub(harness, "codex-cfg", CODEX_STUB))

    outcome = harness["orchestrator"].run(
        config(harness, agent_parameters={"not_a_real_option": 1})
    )

    assert outcome.state is RunState.INVALID_CONFIGURATION
    assert invocations(harness) == 0, "an invalid configuration never starts the agent"


def test_unknown_agent_has_its_own_state(harness: dict) -> None:
    outcome = harness["orchestrator"].run(config(harness, agent_id="does-not-exist"))

    assert outcome.state is RunState.INVALID_CONFIGURATION


def test_a_passed_run_records_the_workspace_and_the_evaluation(harness: dict) -> None:
    use_stub(harness, copy_stub(harness, "codex-record", FIXER_STUB))
    context_seen: list[dict] = []

    orchestrator = harness["orchestrator"]
    original = orchestrator._creating_workspace

    def spy(cfg, ctx):
        result = original(cfg, ctx)
        context_seen.append(ctx.as_record())
        return result

    orchestrator._creating_workspace = spy  # type: ignore[method-assign]
    outcome = orchestrator.run(config(harness))

    assert outcome.state is RunState.COMPLETED
    record = context_seen[-1]
    assert Path(record["workspace_path"]).is_dir()
    assert record["state"] == RunState.CREATING_WORKSPACE.value


def test_lifecycle_table_is_explicit() -> None:
    assert transition_allowed(RunState.PENDING, RunState.PREPARING)
    assert not transition_allowed(RunState.PENDING, RunState.EXECUTING)
    assert transition_allowed(RunState.EXECUTING, RunState.FAILED)
    assert not transition_allowed(RunState.COMPLETED, RunState.FAILED)
    for current in FORWARD_CHAIN[:-1]:
        assert any(transition_allowed(current, target) for target in RunState)
    for terminal in TERMINAL_STATES:
        assert not any(transition_allowed(terminal, other) for other in RunState)
