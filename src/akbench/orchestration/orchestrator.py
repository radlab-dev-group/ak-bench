"""The run orchestrator (plan section 15).

It drives one run through the lifecycle using only generic contracts: the agent
registry and adapter, the runtime registry and execution mode, the workspace
manager and the evaluator engine. There is no agent-specific code here — that
is what makes a new agent a descriptor plus an adapter rather than a change to
the runner.

Two rules from the plan are enforced structurally, not by convention:

- **agent failures are never retried** — only infrastructure failures are, and
  only when the caller configured a retry budget, and every attempt is recorded;
- **an infrastructure failure is never reported as an agent failure** — the
  lifecycle has separate terminal states, so a benchmark run cannot be silently
  scored against the agent.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from akbench.agents.contract import AgentConfig, AgentStatus
from akbench.agents.errors import AgentConfigError
from akbench.agents.registry import AgentRegistry, validate_agent_config
from akbench.core.errors import AKBenchmarkError
from akbench.core.time import utc_now
from akbench.datasets.workspace import WorkspaceManager
from akbench.evaluators.registry import EvaluatorRegistry
from akbench.evaluators.task_evaluation import evaluate_task
from akbench.orchestration.errors import RunPreparationError
from akbench.orchestration.lifecycle import RunContext, RunOutcome, RunState
from akbench.runtime.contract import ExecutionMode
from akbench.runtime.registry import RuntimeRegistry


@dataclass(frozen=True)
class OrchestrationConfig:
    """What one run needs: the task, the agent, the mode and the limits.

    ``infrastructure_retries`` is the explicit retry budget of plan 15. It
    defaults to zero: retrying an agent failure would measure the retry rather
    than the agent.
    """

    task: Any  # LoadedTask; typed loosely to avoid a datasets/orchestration cycle
    agent_id: str
    agent_version: str | None = None
    mode: str = ExecutionMode.DIRECT.value
    runtime_id: str | None = None
    agent_parameters: dict[str, Any] = field(default_factory=dict)
    workspace_id: str | None = None
    artifacts_dir: Path | None = None
    evaluation_dir: Path | None = None
    agent_timeout: float | None = None
    evaluation_timeout: float | None = None
    infrastructure_retries: int = 0
    apply_mutation: bool = True
    cleanup_workspace: bool = False
    task_text: str | None = None


class RunOrchestrator:
    """Executes one run and reports its terminal state.

    Dependencies are injected: the registries and managers come from the
    caller, so a test can pass a stub adapter and a local evaluator while the
    production CLI passes the real ones.
    """

    def __init__(
        self,
        *,
        agents: AgentRegistry,
        runtimes: RuntimeRegistry | None = None,
        workspaces: WorkspaceManager | None = None,
        evaluators: EvaluatorRegistry | None = None,
    ) -> None:
        self.agents = agents
        self.runtimes = runtimes
        self.workspaces = workspaces
        self.evaluators = evaluators

    def run(self, config: OrchestrationConfig) -> RunOutcome:
        """Run once through the lifecycle; never raises for a normal failure."""
        context = RunContext(
            run_uid=_run_uid(),
            task_uid=config.task.uid,
            agent_id=config.agent_id,
            mode=config.mode,
            runtime_id=config.runtime_id,
            started_at=utc_now(),
        )
        return self._run_with_retries(config, context)

    # ------------------------------------------------------------- retries

    def _run_with_retries(
        self, config: OrchestrationConfig, context: RunContext
    ) -> RunOutcome:
        attempt = 0
        while True:
            outcome = self._run_once(config, context, attempt=attempt)
            if outcome.ok or outcome.state is not RunState.INFRASTRUCTURE_ERROR:
                return replace(outcome, record=context.as_record())
            if attempt >= config.infrastructure_retries:
                return replace(outcome, record=context.as_record())
            attempt += 1
            context.history.record(
                context.state,
                f"infrastructure retry {attempt}/{config.infrastructure_retries}",
            )

    # ------------------------------------------------------------- lifecycle

    def _run_once(
        self, config: OrchestrationConfig, context: RunContext, *, attempt: int
    ) -> RunOutcome:
        context.state = RunState.PENDING
        context.history.record(RunState.PENDING, f"attempt {attempt + 1}")

        prepared = self._preparing(config, context)
        if isinstance(prepared, RunOutcome):
            return prepared
        entry, agent_config = prepared

        session = None
        adapter = None
        try:
            adapter = entry.adapter()
            workspace = self._creating_workspace(config, context)
            if isinstance(workspace, RunOutcome):
                return workspace

            session = adapter.start_session(agent_config, workspace)
            context.transition(RunState.STARTING_AGENT, "agent session opened")

            context.transition(RunState.EXECUTING, "task submitted")
            adapter.submit_task(session, self._task_text(config))
            adapter.wait_for_completion(session, timeout=config.agent_timeout)
            result = adapter.close_session(session)

            context.session_id = result.session_id
            context.agent_version = result.agent_version
            context.agent_status = result.status.value
            context.exit_code = result.exit_code
            context.observations = dict(result.observations) or None

            context.transition(RunState.COLLECTING, "observations collected")

            terminal = _terminal_state_for_agent(result.status.value)
            if terminal is not RunState.COMPLETED:
                context.failure_class = (
                    result.failure_class.value if result.failure_class else None
                )
                context.error_message = _first_line(result.final_message)
                context.finish(terminal, f"agent status {result.status.value}")
                return RunOutcome(context.run_uid, terminal, ok=False, detail=context.error_message)

            return self._evaluating(config, context, workspace)
        except AKBenchmarkError as exc:
            return self._fail(config, context, exc, adapter=adapter, session=session)
        except Exception as exc:  # unexpected: record it, never lose the run
            return self._fail(config, context, exc, adapter=adapter, session=session)
        finally:
            self._cleanup(config, context)

    # ---------------------------------------------------------- each step

    def _preparing(
        self, config: OrchestrationConfig, context: RunContext
    ) -> tuple[object, AgentConfig] | RunOutcome:
        """Resolve the agent, validate its configuration and the environment."""
        context.transition(RunState.PREPARING, "resolving agent")
        try:
            entry = self.agents.resolve(config.agent_id, config.agent_version)
        except AKBenchmarkError as exc:
            return self._invalid_config(context, exc)

        context.transition(RunState.VALIDATING, "validating configuration")
        if config.artifacts_dir is None:
            return self._invalid_config(
                context,
                RunPreparationError("an artifacts_dir is required to record agent output"),
            )
        agent_config = AgentConfig(
            agent_id=entry.descriptor.id,
            parameters=dict(config.agent_parameters),
            artifacts_dir=config.artifacts_dir,
            runtime=self._binding(config),
        )
        try:
            validate_agent_config(entry.descriptor, agent_config)
        except AKBenchmarkError as exc:
            return self._invalid_config(context, exc)

        # The adapter's own environment check (binary present, credentials set):
        # a configuration problem, reported before any workspace or process.
        try:
            entry.adapter().validate_environment(agent_config)
        except AgentConfigError as exc:
            return self._invalid_config(context, exc)
        except AKBenchmarkError as exc:
            return self._infrastructure(context, exc)

        # The runtime step is only meaningful when the mode names a runtime.
        if config.mode != ExecutionMode.DIRECT.value:
            context.transition(RunState.CONFIGURING_RUNTIME, f"runtime {config.runtime_id}")
            outcome = self._checking_runtime(config, context)
            if outcome is not None:
                return outcome
        else:
            # The state is part of the chain even without a runtime: skipping it
            # would make the recorded history differ between modes.
            context.transition(RunState.CONFIGURING_RUNTIME, "no runtime in direct mode")
        return entry, agent_config

    def _checking_runtime(self, config: OrchestrationConfig, context: RunContext):
        if self.runtimes is None or config.runtime_id is None:
            return self._infrastructure(
                context, RunPreparationError("the run mode names no runtime")
            )
        try:
            entry = self.runtimes.resolve(config.runtime_id)
            manager = entry.manager()
            healthy = manager.healthcheck()
        except AKBenchmarkError as exc:
            return self._infrastructure(context, exc)
        if not healthy:
            return self._infrastructure(
                context,
                RunPreparationError(f"runtime {config.runtime_id} is not healthy"),
            )
        return None

    def _creating_workspace(self, config: OrchestrationConfig, context: RunContext):
        context.transition(RunState.CREATING_WORKSPACE, "preparing task workspace")
        if self.workspaces is None:
            return self._infrastructure(
                context, RunPreparationError("no workspace manager is configured")
            )
        workspace_id = config.workspace_id or f"{config.task.task.id}-{uuid.uuid4().hex[:8]}"
        try:
            prepared = self.workspaces.prepare(
                config.task.task,
                workspace_id,
                task_dir=config.task.path,
                apply_mutation=config.apply_mutation,
            )
        except AKBenchmarkError as exc:
            return self._infrastructure(context, exc)
        context.history.events[-1]["note"] = f"workspace {prepared.workspace_id}"
        context.history.events[-1]["base_commit"] = prepared.base_commit
        context.history.events[-1]["fingerprint"] = prepared.fingerprint
        context.workspace_path = str(prepared.path)
        return prepared.path

    def _evaluating(
        self, config: OrchestrationConfig, context: RunContext, workspace: Path
    ) -> RunOutcome:
        context.transition(RunState.EVALUATING, "running the task evaluator")
        if self.evaluators is None:
            return self._evaluation_error(context, RunPreparationError("no evaluators configured"))
        out_dir = config.evaluation_dir or (
            config.artifacts_dir / "evaluation" if config.artifacts_dir else None
        )
        if out_dir is None:
            return self._evaluation_error(
                context, RunPreparationError("no evaluation output directory configured")
            )
        try:
            result = evaluate_task(
                config.task,
                workspace,
                Path(out_dir),
                registry=self.evaluators,
                timeout=config.evaluation_timeout,
            )
        except AKBenchmarkError as exc:
            return self._evaluation_error(context, exc)

        context.evaluation = result.as_dict()
        if result.verdict.value in {"evaluator_error", "infrastructure_error"}:
            return self._evaluation_error(
                context,
                RunPreparationError(f"evaluator reported {result.verdict.value}"),
            )

        context.finish(RunState.COMPLETED, f"evaluation {result.verdict.value}")
        return RunOutcome(
            context.run_uid,
            RunState.COMPLETED,
            ok=result.verdict.value == "passed",
            detail=f"evaluation {result.verdict.value}",
        )

    # ------------------------------------------------------------ failures

    def _fail(
        self,
        config: OrchestrationConfig,
        context: RunContext,
        exc: Exception,
        *,
        adapter=None,
        session=None,
    ) -> RunOutcome:
        """Classify an exception into the right terminal state (plan rule 11)."""
        if adapter is not None and session is not None:
            with suppress(Exception):  # cleanup must not mask the original failure
                adapter.close_session(session)

        text = str(exc).lower()
        if "timeout" in text or "timed out" in text:
            state = RunState.TIMEOUT
        elif isinstance(exc, RunPreparationError):
            state = RunState.INVALID_CONFIGURATION
        else:
            state = RunState.INFRASTRUCTURE_ERROR
        context.error_message = str(exc)
        context.finish(state, type(exc).__name__)
        return RunOutcome(context.run_uid, state, ok=False, detail=str(exc))

    def _invalid_config(self, context: RunContext, exc: Exception) -> RunOutcome:
        context.error_message = str(exc)
        context.finish(RunState.INVALID_CONFIGURATION, type(exc).__name__)
        return RunOutcome(context.run_uid, RunState.INVALID_CONFIGURATION, False, str(exc))

    def _infrastructure(self, context: RunContext, exc: Exception) -> RunOutcome:
        context.error_message = str(exc)
        context.finish(RunState.INFRASTRUCTURE_ERROR, type(exc).__name__)
        return RunOutcome(context.run_uid, RunState.INFRASTRUCTURE_ERROR, False, str(exc))

    def _evaluation_error(self, context: RunContext, exc: Exception) -> RunOutcome:
        context.error_message = str(exc)
        context.finish(RunState.EVALUATION_ERROR, type(exc).__name__)
        return RunOutcome(context.run_uid, RunState.EVALUATION_ERROR, False, str(exc))

    # --------------------------------------------------------------- helpers

    def _binding(self, config: OrchestrationConfig):
        if config.mode == ExecutionMode.DIRECT.value or not config.runtime_id:
            return None
        from akbench.agents.catalog import binding_from_runtime

        entry = self.runtimes.resolve(config.runtime_id)
        return binding_from_runtime(entry.descriptor)

    def _task_text(self, config: OrchestrationConfig) -> str:
        """The prompt for the agent: an override, or the task's own description."""
        if config.task_text:
            return config.task_text
        description = Path(config.task.path) / "description.md"
        if description.is_file():
            return description.read_text(encoding="utf-8").strip()
        declared = getattr(config.task.task, "description", None)
        if declared:
            return str(declared).strip()
        raise RunPreparationError(f"task {config.task.uid} provides no prompt text")

    def _cleanup(self, config: OrchestrationConfig, context: RunContext) -> None:
        if not config.cleanup_workspace or self.workspaces is None:
            return
        if not context.workspace_path:
            return
        try:
            self.workspaces.cleanup(Path(context.workspace_path))
        except AKBenchmarkError:
            # cleanup is best effort; losing a scratch directory is not a run failure
            context.history.record(context.state, "workspace cleanup failed")


def _terminal_state_for_agent(agent_status: str) -> RunState:
    """Map the adapter's normalized status onto the run lifecycle."""
    return {
        AgentStatus.COMPLETED.value: RunState.COMPLETED,
        AgentStatus.FAILED.value: RunState.FAILED,
        AgentStatus.TIMED_OUT.value: RunState.TIMEOUT,
        AgentStatus.CANCELLED.value: RunState.CANCELLED,
        AgentStatus.INFRASTRUCTURE_ERROR.value: RunState.INFRASTRUCTURE_ERROR,
    }.get(agent_status, RunState.FAILED)


def _first_line(text: str | None) -> str | None:
    if not text:
        return None
    return text.strip().splitlines()[0] if text.strip() else None


def _run_uid() -> str:
    return f"run-{utc_now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
