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

import threading
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from akbench.agents.contract import AgentConfig, AgentStatus
from akbench.agents.errors import AgentConfigError
from akbench.agents.registry import (
    AgentRegistry,
    effective_parameters,
    validate_agent_config,
)
from akbench.core.errors import AKBenchmarkError
from akbench.core.time import utc_now
from akbench.datasets.workspace import WorkspaceManager
from akbench.evaluators.registry import EvaluatorRegistry
from akbench.evaluators.task_evaluation import evaluate_task
from akbench.orchestration.cancellation import CancelToken
from akbench.orchestration.errors import RunPreparationError
from akbench.orchestration.lifecycle import RunContext, RunOutcome, RunState
from akbench.orchestration.packaging import collect_and_package_artifacts
from akbench.runtime.contract import ExecutionMode, Lifecycle
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
    #: Factor values the runtime itself has to apply (plugin toggles). They are
    #: not agent parameters: a managed instance reads them as its own process
    #: configuration, which is what turns a requested value into an applied one.
    runtime_environment: dict[str, Any] = field(default_factory=dict)
    #: Environment the variant declares for the runtime process verbatim, from
    #: the combination's ``runtime_env``. Which plugins a process loads is
    #: fixed when it starts, so this is how a variant says which plugins it has.
    runtime_env: dict[str, str] = field(default_factory=dict)
    workspace_id: str | None = None
    #: The environment this run declares it executes in (plan 9, 14): its
    #: identity, sandbox kind and image, resolved from the descriptor by the
    #: caller. Recorded in the run so a month later the manifest can say where
    #: the run happened instead of leaving the reader to assume the host.
    environment: dict[str, Any] | None = None
    artifacts_dir: Path | None = None
    evaluation_dir: Path | None = None
    agent_timeout: float | None = None
    evaluation_timeout: float | None = None
    infrastructure_retries: int = 0
    apply_mutation: bool = True
    cleanup_workspace: bool = False
    task_text: str | None = None
    #: Called with the state value on every transition of this run. The CLI
    #: shows the phase behind its elapsed-time counter; it observes the run and
    #: changes nothing about it, and it is not recorded.
    on_transition: Callable[[str], None] | None = None
    #: A request to stop this run. Checked between phases, and while the agent
    #: works it interrupts the agent process (``adapter.cancel``) rather than
    #: waiting out the timeout. A cancelled run ends in ``cancelled``, which is
    #: an outcome, not an error: the artifacts stay and the record says why.
    cancel_token: CancelToken | None = None


#: Environment variables whose value is worth a line in the run's history: they
#: say what the runtime instance of this run actually was.
NOTABLE_RUNTIME_ENVIRONMENT = ("LLM_ROUTER_UTILS_PLUGINS_PIPELINE",)


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
            requested_model=_requested_model(config.agent_parameters),
            environment=config.environment,
            started_at=utc_now(),
            on_transition=config.on_transition,
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
        entry, agent_config, runtime = prepared

        session = None
        adapter = None
        watcher = None
        try:
            cancelled = self._cancelled(config, context, "before the agent was started")
            if cancelled is not None:
                return cancelled

            adapter = entry.adapter()
            workspace = self._creating_workspace(config, context)
            if isinstance(workspace, RunOutcome):
                return workspace

            session = adapter.start_session(agent_config, workspace)
            context.transition(RunState.STARTING_AGENT, "agent session opened")

            cancelled = self._cancelled(config, context, "before the task was submitted")
            if cancelled is not None:
                return cancelled

            context.transition(RunState.EXECUTING, "task submitted")
            adapter.submit_task(session, self._task_text(config))
            watcher = _watch_cancel(config, adapter, session)
            adapter.wait_for_completion(session, timeout=config.agent_timeout)
            result = adapter.close_session(session)
            if config.cancel_token is not None and config.cancel_token.cancelled:
                return self._finish_cancelled(config, context, result.final_message)

            context.session_id = result.session_id
            context.agent_version = result.agent_version
            context.agent_status = result.status.value
            context.exit_code = result.exit_code
            context.observations = dict(result.observations) or None
            # A flat total is a sum, so it is only stated when the parts exist;
            # an adapter that reports parts but no total keeps the total missing
            # rather than having one invented for it (plan 6.3).
            if (
                result.usage is not None
                and result.usage.total_tokens is not None
                and context.observations
                and context.observations.get("token_usage") is not None
            ):
                context.observations["token_usage"]["total_tokens"] = result.usage.total_tokens

            context.transition(RunState.COLLECTING, "observations collected")

            collect_and_package_artifacts(
                workspace_dir=workspace,
                artifacts_dir=config.artifacts_dir,
            )

            terminal = _terminal_state_for_agent(result.status.value)
            if terminal is not RunState.COMPLETED:
                context.failure_class = (
                    result.failure_class.value if result.failure_class else None
                )
                context.error_message = _first_line(result.final_message)
                context.finish(terminal, f"agent status {result.status.value}")
                return RunOutcome(context.run_uid, terminal, ok=False, detail=context.error_message)

            outcome = self._evaluating(config, context, workspace)
            eval_target = config.evaluation_dir or (
                config.artifacts_dir / "evaluation" if config.artifacts_dir else None
            )
            collect_and_package_artifacts(
                workspace_dir=None,
                artifacts_dir=config.artifacts_dir,
                evaluation_dir=eval_target,
            )
            return outcome
        except AKBenchmarkError as exc:
            return self._fail(config, context, exc, adapter=adapter, session=session)
        except Exception as exc:  # unexpected: record it, never lose the run
            return self._fail(config, context, exc, adapter=adapter, session=session)
        finally:
            if watcher is not None:
                watcher.cancel.set()
            self._recording_model_evidence(runtime, context)
            self._stopping_runtime(runtime, context)
            self._cleanup(config, context)

    # ---------------------------------------------------------- each step

    def _preparing(
        self, config: OrchestrationConfig, context: RunContext
    ) -> tuple[object, AgentConfig, object] | RunOutcome:
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
        # The descriptor's declared defaults are part of the configuration, so
        # they are filled before validation and recorded as what was applied:
        # an agent left on an adapter's own fallback is an unrecorded choice.
        parameters = effective_parameters(entry.descriptor, config.agent_parameters)
        agent_config = AgentConfig(
            agent_id=entry.descriptor.id,
            parameters=parameters,
            artifacts_dir=config.artifacts_dir,
            runtime=self._binding(config),
        )
        context.agent_parameters = dict(parameters)
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
        runtime = None
        if config.mode != ExecutionMode.DIRECT.value:
            context.transition(RunState.CONFIGURING_RUNTIME, f"runtime {config.runtime_id}")
            runtime, outcome = self._checking_runtime(config, context)
            if outcome is not None:
                return outcome
        else:
            # The state is part of the chain even without a runtime: skipping it
            # would make the recorded history differ between modes.
            context.transition(RunState.CONFIGURING_RUNTIME, "no runtime in direct mode")
        return entry, agent_config, runtime

    def _checking_runtime(
        self, config: OrchestrationConfig, context: RunContext
    ) -> tuple[object, RunOutcome | None]:
        """Bring the runtime up and hand the caller what it must stop again.

        A **managed** instance is started here, per run, with this run's factor
        values in its environment and its log inside the run's artifacts: the
        variant's plugin configuration is then a property of a process this run
        owned, and the log is the evidence. An **external** instance is only
        health-checked, because starting or reconfiguring a shared router would
        change the experiment for everybody (plan section 13).
        """
        if self.runtimes is None or config.runtime_id is None:
            return None, self._infrastructure(
                context, RunPreparationError("the run mode names no runtime")
            )
        try:
            entry = self.runtimes.resolve(config.runtime_id)
            manager = entry.manager(
                factor_values=dict(config.runtime_environment),
                runtime_env=dict(config.runtime_env),
                log_dir=config.artifacts_dir,
            )
        except AKBenchmarkError as exc:
            return None, self._infrastructure(context, exc)

        # The manager may carry either Lifecycle vocabulary (contract or
        # descriptor); compare by value, never by identity.
        manager_lifecycle = getattr(manager, "lifecycle", None)
        if manager_lifecycle is not None and str(manager_lifecycle) == Lifecycle.MANAGED.value:
            try:
                manager.start()
            except AKBenchmarkError as exc:
                manager.stop()
                return None, self._infrastructure(context, exc)
            log_path = getattr(manager, "log_path", None)
            declared = getattr(manager, "declared_environment", None)
            context.runtime_environment = dict(declared()) if callable(declared) else None
            notes = [f"managed runtime {config.runtime_id} started"]
            if log_path:
                notes.append(f"log {Path(log_path).name}")
            for name in NOTABLE_RUNTIME_ENVIRONMENT:
                if context.runtime_environment and name in context.runtime_environment:
                    notes.append(f"{name}={context.runtime_environment[name]}")
            context.history.record(context.state, ", ".join(notes))
            self._recording_served_models(manager, context)
            return manager, None

        try:
            healthy = manager.healthcheck()
        except AKBenchmarkError as exc:
            manager.stop()
            return None, self._infrastructure(context, exc)
        if not healthy:
            manager.stop()
            return None, self._infrastructure(
                context,
                RunPreparationError(f"runtime {config.runtime_id} is not healthy"),
            )
        self._recording_served_models(manager, context)
        return manager, None

    def _recording_served_models(self, manager: object, context: RunContext) -> None:
        """Ask the instance which models it serves, and record what it answers.

        Inventory is the weakest model evidence there is — it says what the
        instance can serve, not what served this run — so a failure to read it
        is a note, never a run-ending error.
        """
        list_models = getattr(manager, "list_models", None)
        if not callable(list_models):
            return
        try:
            models = list_models()
        except AKBenchmarkError as exc:
            context.history.record(context.state, f"model inventory unreadable: {exc}")
            return
        context.served_models = list(models) if models is not None else None
        if models is None:
            context.history.record(context.state, "model inventory unreadable")

    def _recording_model_evidence(self, manager: object, context: RunContext) -> None:
        """Read the instance's own account of the models it handled.

        This must happen while the run still owns the process and its log, so
        it is collected before the runtime is stopped.
        """
        evidence = getattr(manager, "model_request_evidence", None)
        if not callable(evidence):
            return
        try:
            recorded = evidence()
        except AKBenchmarkError as exc:
            context.history.record(context.state, f"model evidence failed: {exc}")
            return
        if isinstance(recorded, dict):
            context.model_evidence = recorded

    def _stopping_runtime(self, manager: object, context: RunContext) -> None:
        """Stop the managed instance this run started; losing it is a bug."""
        if manager is None:
            return
        try:
            manager.stop()
        except AKBenchmarkError as exc:
            context.history.record(context.state, f"runtime stop failed: {exc}")
        else:
            context.history.record(context.state, "runtime stopped")

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

    # ------------------------------------------------------------ cancellation

    def _cancelled(
        self, config: OrchestrationConfig, context: RunContext, stage: str
    ) -> RunOutcome | None:
        """The run between two phases: stop here if the operator asked to."""
        token = config.cancel_token
        if token is None or not token.cancelled:
            return None
        reason = token.reason or "cancelled"
        context.finish(RunState.CANCELLED, f"cancelled {stage}: {reason}")
        return RunOutcome(context.run_uid, RunState.CANCELLED, ok=False, detail=reason)

    def _finish_cancelled(
        self, config: OrchestrationConfig, context: RunContext, final_message: str | None
    ) -> RunOutcome:
        """A run interrupted while the agent worked: an outcome, not a failure.

        The agent was asked to stop and did, so what it produced is kept and
        the run is recorded cancelled with the reason. Judging half an answer
        with the hidden tests would turn an operator's decision into the
        agent's failure, which plan rule 11 forbids in the same breath as
        counting an infrastructure error against the agent.
        """
        token = config.cancel_token
        reason = (token.reason if token is not None else None) or "cancelled while executing"
        context.error_message = reason
        context.finish(RunState.CANCELLED, f"interrupted: {reason}")
        detail = final_message or reason
        return RunOutcome(context.run_uid, RunState.CANCELLED, ok=False, detail=detail)

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


class _CancelWatcher:
    """Interrupts the agent when the token fires, and stops watching after.

    The agent's own wait is blocking, so cancellation needs a second thread:
    it waits for either the token or the run finishing, and only asks the
    agent to stop in the first case. ``stop`` is called from the run's
    ``finally``, so a normal end never leaves a thread behind.
    """

    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.triggered = False
        self.thread: threading.Thread | None = None


def _watch_cancel(config: OrchestrationConfig, adapter: Any, session: Any) -> _CancelWatcher | None:
    """Watch the run's cancel token against one agent session."""
    token = config.cancel_token
    watcher = _CancelWatcher()
    if token is None:
        return watcher

    def _loop() -> None:
        # Two events race on purpose: the token interrupts the agent, the
        # watcher's own event ends the thread when the run finishes normally.
        # A run that finishes without a cancellation must leave the agent
        # alone, so the token is only ever consulted while watching.
        while not watcher.cancel.is_set():
            if token.wait(0.25):
                if not watcher.cancel.is_set():
                    watcher.triggered = True
                    with suppress(Exception):
                        adapter.cancel(session)
                return

    watcher.thread = threading.Thread(target=_loop, daemon=True, name="akbench-run-cancel")
    watcher.thread.start()
    return watcher


def _run_uid() -> str:
    return f"run-{utc_now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _requested_model(agent_parameters: dict[str, Any]) -> str | None:
    model = agent_parameters.get("model")
    return str(model) if model else None
