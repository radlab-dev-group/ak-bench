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
        resolved = LlmRouterOptions(**base)
        if descriptor is not None:
            body = descriptor.runtime
            resolved = LlmRouterOptions(
                base_url=resolved.base_url or (body.base_url or ""),
                healthcheck_path=resolved.healthcheck_path or (body.healthcheck_path or "/health"),
                metrics_path=resolved.metrics_path or (body.metrics_path or "/metrics"),
                api_key_env=resolved.api_key_env
                or (body.required_env[0] if body.required_env else None),
                timeout=resolved.timeout,
                lifecycle=resolved.lifecycle,
                config_file=resolved.config_file,
                start_command=list(resolved.start_command),
                ready_timeout=resolved.ready_timeout,
                stop_grace=resolved.stop_grace,
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
        self._process = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._started = True
        if not self._wait_until_ready(self.options.ready_timeout):
            self.stop()
            raise RuntimeLayerError(
                f"runtime {self.runtime_id!r} did not become healthy within "
                f"{self.options.ready_timeout}s"
            )

    def stop(self) -> None:
        """Stop the managed instance this adapter started; ignore external ones."""
        process = self._process
        self._started = False
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            deadline = time.time() + self.options.stop_grace
            while process.poll() is None and time.time() < deadline:
                time.sleep(0.1)
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        self._process = None

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
