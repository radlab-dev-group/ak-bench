"""LLM Router runtime adapter (descriptor adapter id ``llm_router``).

Every claim encoded here comes from ``docs/ROUTER_INTEGRATION.md``; nothing is
assumed about endpoints that were not checked:

- ``GET /health`` answers ``200`` with ``{"body":"healthy",...}`` — the only
  usable healthcheck (``/healthz`` and ``/health/live`` are denied by policy);
- ``GET /v1/models`` lists the served models, but **not** the aliases
  (``auto_codex`` works and is absent), so the inventory is not the whole
  value space of the model dimension;
- the effective configuration cannot be read over HTTP (``/config`` and
  friends are denied), which is why ``read_configuration`` reports
  ``unsupported`` unless a host-side model configuration file is configured;
- there is no configuration write endpoint at all, so ``apply_configuration``
  refuses rather than pretending;
- ``external`` instances are shared: AK-Bench must not start, stop or reconfigure
  them, and experiments there are marked unverified (plan section 13).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from akbench.descriptors.runtime import Lifecycle, RuntimeDescriptor
from akbench.runtime.contract import (
    RuntimeConfigReport,
    RuntimeState,
    VerificationStatus,
)
from akbench.runtime.errors import (
    CapabilityNotSupported,
    RuntimeConfigError,
)
from akbench.runtime.errors import RuntimeError as RuntimeLayerError
from akbench.runtime.http import HttpError, HttpResponse, get_json

ADAPTER_ID = "llm_router"
MODELS_PATH = "/v1/models"


@dataclass(frozen=True)
class LlmRouterOptions:
    """Endpoints and credentials for one router instance.

    ``config_file`` is only meaningful when AK-Bench runs on the router host:
    it points at the model configuration the process actually loaded
    (``LLM_ROUTER_MODELS_CONFIG``). Without it the effective configuration
    cannot be read and the report says so.
    """

    base_url: str = ""
    healthcheck_path: str = "/health"
    metrics_path: str = "/metrics"
    api_key_env: str | None = None
    timeout: float = 10.0
    lifecycle: Lifecycle = Lifecycle.EXTERNAL
    config_file: Path | None = None
    #: Command that starts a managed instance, e.g. a ``docker run ...`` argv.
    start_command: list[str] = field(default_factory=list)
    #: Working directory of the launched process (the router resolves its
    #: models config and prompts directory against it).
    cwd: Path | None = None
    #: Environment applied to the launched process on top of the ambient one.
    env: dict[str, str] = field(default_factory=dict)
    #: Factor id -> environment variable, so a variant value becomes a real
    #: process configuration instead of a recorded request.
    factor_env: dict[str, str] = field(default_factory=dict)
    #: Factor values of the run being started, mapped through ``factor_env``.
    factor_values: dict[str, Any] = field(default_factory=dict)
    #: Where the launched process writes its log; ``None`` discards it.
    log_file: Path | None = None
    #: Directory the log name is resolved against, so the runner decides where
    #: a run's evidence lives and the descriptor only decides what it is called.
    log_dir: Path | None = None
    #: Seconds to wait for a managed instance to become healthy.
    ready_timeout: float = 120.0
    stop_grace: float = 15.0


class LlmRouterAdapter:
    """Manages (or merely observes) one LLM Router instance."""

    adapter_id = ADAPTER_ID

    def __init__(
        self,
        descriptor: RuntimeDescriptor | None = None,
        options: LlmRouterOptions | None = None,
        **overrides: Any,
    ) -> None:
        """``overrides`` are option fields, so a registry factory can pass them
        as keyword arguments without naming the concrete adapter."""
        self.descriptor = descriptor
        base = dict(options.__dict__) if options is not None else {}
        base.update({k: v for k, v in overrides.items() if v is not None})
        given = LlmRouterOptions(**base)
        defaults = LlmRouterOptions()
        body = descriptor.runtime if descriptor is not None else None
        launch = body.managed if body is not None else None

        def pick(name: str, declared: Any) -> Any:
            """An explicitly passed option wins over the descriptor.

            Only non-``None`` options count as passed, because the registry
            factory passes every option it knows and an unset one must not
            erase what the descriptor declares.
            """
            if name in base:
                return getattr(given, name)
            if declared is not None:
                return declared
            return getattr(defaults, name)

        resolved = LlmRouterOptions(
            base_url=pick("base_url", body.base_url if body else None),
            healthcheck_path=pick("healthcheck_path", body.healthcheck_path if body else None),
            metrics_path=pick("metrics_path", body.metrics_path if body else None),
            api_key_env=pick(
                "api_key_env", body.required_env[0] if body and body.required_env else None
            ),
            timeout=pick("timeout", None),
            lifecycle=pick("lifecycle", _declared_lifecycle(body)),
            config_file=pick(
                "config_file", Path(launch.config_file) if launch and launch.config_file else None
            ),
            start_command=pick(
                "start_command", list(launch.command) if launch and launch.command else None
            ),
            cwd=pick("cwd", Path(launch.cwd) if launch and launch.cwd else None),
            env={**(launch.env if launch else {}), **given.env},
            factor_env=pick(
                "factor_env", dict(launch.factor_env) if launch and launch.factor_env else None
            ),
            factor_values=given.factor_values,
            log_file=pick(
                "log_file", Path(launch.log_file) if launch and launch.log_file else None
            ),
            # The directory is a property of the run, not of the runtime: the
            # descriptor names the log, and the runner decides where the
            # evidence of one run lives.
            log_dir=Path(given.log_dir) if given.log_dir is not None else None,
            ready_timeout=pick("ready_timeout", launch.ready_timeout if launch else None),
            stop_grace=pick("stop_grace", launch.stop_grace if launch else None),
        )
        if not resolved.base_url:
            raise RuntimeConfigError(
                "llm_router needs a base_url (from the descriptor or the options)"
            )
        self.options = resolved
        self.base_url = resolved.base_url.rstrip("/")
        self.runtime_id = descriptor.id if descriptor is not None else ADAPTER_ID
        self.lifecycle = resolved.lifecycle
        self._process: subprocess.Popen | None = None
        self._started = False
        self.log_path: Path | None = None
        self.log_handle = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Start a managed instance. External instances are never touched."""
        if self.lifecycle is not Lifecycle.MANAGED:
            raise CapabilityNotSupported(
                f"runtime {self.runtime_id!r} is lifecycle=external: AK-Bench does not "
                "start, stop or reconfigure a shared instance (plan section 13)"
            )
        if not self.options.start_command:
            raise CapabilityNotSupported(
                f"runtime {self.runtime_id!r} is managed but declares no start command; "
                "configure the command that launches the instance"
            )
        if self._process is not None:
            raise RuntimeLayerError(f"runtime {self.runtime_id!r} is already started")

        argv = list(self.options.start_command)
        if len(argv) == 1:
            argv = shlex.split(argv[0])
        self._open_log(self.options.log_file)
        self._process = subprocess.Popen(
            argv,
            cwd=str(self.options.cwd) if self.options.cwd else None,
            env=self.process_environment(),
            stdout=(self.log_handle or subprocess.DEVNULL),
            stderr=(self.log_handle or subprocess.DEVNULL),
            start_new_session=True,
        )
        self._started = True
        if not self._wait_until_ready(self.options.ready_timeout):
            exit_code = self._process.returncode if self._process else None
            log_note = f" (see {self.log_path})" if self.log_path else ""
            if self._process is not None and exit_code is not None:
                self.stop()
                raise RuntimeLayerError(
                    f"runtime {self.runtime_id!r} exited with code {exit_code} "
                    f"before becoming healthy{log_note}"
                )
            self.stop()
            raise RuntimeLayerError(
                f"runtime {self.runtime_id!r} did not become healthy within "
                f"{self.options.ready_timeout}s{log_note}"
            )

    def stop(self) -> None:
        """Stop the managed instance this adapter started; ignore external ones."""
        process = self._process
        self._started = False
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                deadline = time.time() + self.options.stop_grace
                while process.poll() is None and time.time() < deadline:
                    time.sleep(0.1)
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        finally:
            self._process = None
            self._close_log()

    def healthcheck(self) -> bool:
        """True when the router answers its health endpoint as healthy."""
        response = self._get(self.options.healthcheck_path)
        if response is None or not response.ok:
            return False
        return _looks_healthy(response)

    # ---------------------------------------------------------- configuration

    def apply_configuration(self, config: dict[str, Any]) -> None:
        """Refuse: the router exposes no configuration write endpoint (verified)."""
        raise CapabilityNotSupported(
            "llm_router has no configuration write endpoint (checked: /config, "
            "/admin/config and friends are denied by policy); run a managed "
            "instance with its own configuration file instead "
            f"(requested: {sorted(config)})"
        )

    def read_configuration(self) -> RuntimeConfigReport:
        """Read the effective configuration, or report honestly that we cannot.

        Over HTTP this is ``unsupported`` (verified 403). When a host-side
        ``config_file`` is configured and readable, its content is the
        effective model configuration and the report is ``verified``.
        """
        observed: dict[str, Any] = {}
        notes: list[str] = []
        models = self.list_models()
        if models is not None:
            observed["served_models"] = models

        config_file = self.options.config_file
        if config_file is not None:
            path = Path(config_file)
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    notes.append(f"config file {path} could not be parsed: {exc}")
                    return RuntimeConfigReport(
                        effective=None,
                        observed=observed,
                        verification_status=VerificationStatus.UNVERIFIED,
                        notes=notes,
                    )
                observed["config_file"] = str(path)
                return RuntimeConfigReport(
                    requested={},
                    effective=payload if isinstance(payload, dict) else None,
                    observed=observed,
                    verification_status=VerificationStatus.VERIFIED,
                    notes=notes,
                )
            notes.append(
                f"config file {path} is not readable from this host; the effective "
                "configuration cannot be read over HTTP"
            )
        else:
            notes.append(
                "the effective configuration is not readable over HTTP (403 by policy); "
                "configure config_file, or run a managed instance whose files are reachable"
            )

        status = (
            VerificationStatus.UNSUPPORTED
            if not self._configuration_endpoint_reachable()
            else VerificationStatus.UNVERIFIED
        )
        return RuntimeConfigReport(
            requested={},
            effective=None,
            observed=observed,
            verification_status=status,
            notes=notes,
        )

    def verify_configuration(self, expected: dict[str, Any]) -> RuntimeConfigReport:
        """Compare the effective configuration with what the experiment expects.

        Without a readable effective configuration the verdict is
        ``unverified`` — never a silent pass (plan section 13).
        """
        report = self.read_configuration()
        observed = dict(report.observed)
        notes = list(report.notes)

        if report.effective is None:
            return RuntimeConfigReport(
                requested=dict(expected),
                effective=None,
                observed=observed,
                verification_status=VerificationStatus.UNSUPPORTED,
                notes=[*notes, "expected configuration cannot be checked against a "
                       "configuration that cannot be read"],
            )

        mismatches = _diff(expected, report.effective)
        if mismatches:
            observed["mismatches"] = mismatches
            notes.append("expected configuration does not match the effective one")
        return RuntimeConfigReport(
            requested=dict(expected),
            effective=report.effective,
            observed=observed,
            verification_status=VerificationStatus.VERIFIED
            if not mismatches
            else VerificationStatus.UNVERIFIED,
            notes=notes,
        )

    # ---------------------------------------------------- launched process

    def process_environment(self) -> dict[str, str]:
        """Ambient environment, the descriptor's env, then this run's factors.

        Factor values come last on purpose: they are what the experiment varied,
        and a variant that could be overridden by a stray shell variable would
        silently stop being the variant it claims to be.
        """
        environment = dict(os.environ)
        environment.update(self.options.env)
        for factor, name in self.options.factor_env.items():
            if factor not in self.options.factor_values:
                continue
            environment[name] = _as_environment_value(self.options.factor_values[factor])
        return environment

    def _open_log(self, log_file: Path | None):
        """Open the instance log so the run keeps the router's own account.

        The name comes from the descriptor and lands in the directory the runner
        supplied, which is what makes the log of a managed instance an artifact
        of the run that started it rather than a file somebody has to go find.
        """
        if log_file is None:
            return None
        path = Path(log_file)
        if not path.is_absolute() and self.options.log_dir is not None:
            path = Path(self.options.log_dir) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = path
        self.log_handle = path.open("ab")
        return self.log_handle

    def _close_log(self) -> None:
        handle = self.log_handle
        self.log_handle = None
        if handle is not None:
            with suppress(OSError):
                handle.close()

    # ------------------------------------------------------------ observation

    def collect_runtime_state(self) -> RuntimeState:
        """Health, the served model inventory and whether metrics are exposed."""
        models = self.list_models()
        metrics = self._get(self.options.metrics_path)
        details: dict[str, Any] = {}
        health = self._get(self.options.healthcheck_path)
        if health is not None:
            details["healthcheck_status"] = health.status
            details["healthcheck_body"] = health.body.strip()[:200]
        return RuntimeState(
            healthy=_looks_healthy(health) if health is not None else None,
            base_url=self.base_url,
            lifecycle=self.lifecycle,
            models=models or [],
            metrics_available=bool(metrics is not None and metrics.ok),
            details=details,
        )

    def list_models(self) -> list[str] | None:
        """The model inventory, or ``None`` when it cannot be read.

        Aliases are not listed by the router, so this is not the complete set of
        model values an experiment may use.
        """
        response = self._get(MODELS_PATH)
        if response is None or not response.ok:
            return None
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return None
        return sorted(
            {str(item["id"]) for item in data if isinstance(item, dict) and item.get("id")}
        )

    # ---------------------------------------------------------------- private

    def _token(self) -> str | None:
        name = self.options.api_key_env
        if not name:
            return None
        return os.environ.get(name)

    def _get(self, path: str) -> HttpResponse | None:
        url = f"{self.base_url}{path}"
        try:
            return get_json(url, token=self._token(), timeout=self.options.timeout)
        except HttpError as exc:
            self._last_error = str(exc)
            return None

    def _configuration_endpoint_reachable(self) -> bool:
        """Distinguish 'denied by policy' from 'unreachable host'."""
        for path in ("/config", "/admin/config"):
            response = self._get(path)
            if response is None:
                return False
            if response.status in (401, 403):
                return False
            if response.ok:
                return True
        return False

    def _wait_until_ready(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.healthcheck():
                return True
            if self._process is not None and self._process.poll() is not None:
                return False
            time.sleep(0.5)
        return False


def _declared_lifecycle(body: Any) -> Lifecycle | None:
    """The lifecycle of a descriptor that owns its process, else ``None``.

    A descriptor that declares a ``managed`` launch block and no other
    lifecycle is AK-Bench's own instance, so it is managed by default. One that
    also accepts ``external`` stays external: only a managed instance may be
    started or stopped (plan section 13), and an unasked-for start is worse
    than a refused one.
    """
    if body is None or body.managed is None:
        return None
    declared = body.supported_lifecycles
    if Lifecycle.EXTERNAL in declared:
        return None
    return Lifecycle.MANAGED if Lifecycle.MANAGED in declared else None


def _as_environment_value(value: Any) -> str:
    """Render a factor value the way the router's own parsing expects.

    The router reads booleans as ``true``/``false`` (and ``1``/``0``); Python's
    ``str(True)`` would hand it ``True``, which most parsers read as a string.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _looks_healthy(response: HttpResponse | None) -> bool:
    """The verified shape is ``{"body":"healthy","status":true,...}``."""
    if response is None or not response.ok:
        return False
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return "healthy" in response.body.lower()
    if isinstance(payload, dict):
        if payload.get("status") is True:
            return True
        body = payload.get("body")
        return isinstance(body, str) and body.lower() == "healthy"
    return False


def _diff(expected: dict[str, Any], effective: dict[str, Any]) -> list[str]:
    """Dotted paths where ``expected`` and ``effective`` disagree.

    Only the requested keys are compared: the effective configuration carries
    many defaults the experiment does not care about.
    """
    mismatches: list[str] = []

    def walk(prefix: str, want: Any, have: Any) -> None:
        if isinstance(want, dict):
            if not isinstance(have, dict):
                mismatches.append(prefix or "<root>")
                return
            for key, value in want.items():
                walk(f"{prefix}.{key}" if prefix else str(key), value, have.get(key))
            return
        if want != have:
            mismatches.append(prefix or "<root>")

    walk("", expected, effective)
    return mismatches
