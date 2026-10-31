"""Plugin adapter for plugins that run inside the LLM Router.

What can honestly be said about these plugins comes from
``docs/ROUTER_INTEGRATION.md``:

- the router refuses configuration reads (``/config`` and friends are denied),
  so an *effective* value cannot be obtained from a remote instance;
- the ``/metrics`` export carries no per-plugin counter, so no plugin metric
  can be attributed to one run;
- the evidence that does exist is the allowlisted environment of the process
  AK-Bench starts, plus anything a caller injects (a host-side configuration
  reader, a counter source).

So this adapter reads the declared allowlist, records requested and observed
values separately, and reports ``unverified``/``unsupported`` where evidence
does not exist. Verification only happens against injected evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from akbench.descriptors.env import observe_env
from akbench.descriptors.plugin import (
    ConfiguredValue,
    ObservedEnv,
    PluginDescriptor,
    PluginState,
)
from akbench.descriptors.statuses import ValueSource, VerificationStatus
from akbench.plugins.contract import PluginAdapterError, PluginMetric, PluginReport

ADAPTER_ID = "llm_router_plugin"
PROVIDER = "llm-router"

#: Reason used when a declared plugin metric has no source on this instance.
NO_PLUGIN_METRICS = (
    "the router exports no per-plugin counter, so this metric cannot be attributed "
    "to a run (docs/ROUTER_INTEGRATION.md section 7)"
)

#: Returns the effective plugin configuration, or ``None`` when it cannot be
#: read. Host-side only: the router exposes no endpoint for it.
ConfigReader = Callable[[], "Mapping[str, Any] | None"]


class LlmRouterPluginAdapter:
    """Observe, verify and normalize one LLM Router plugin descriptor."""

    adapter_id = ADAPTER_ID

    def __init__(
        self,
        config_reader: ConfigReader | None = None,
        metric_source: Mapping[str, Any] | None = None,
    ) -> None:
        """``config_reader`` and ``metric_source`` are injected evidence.

        Both stay optional because on the shared external instance neither
        exists: a reader would only work on the router host, and a metric
        source appears only once the router exports per-plugin counters.
        """
        self._config_reader = config_reader
        self._metric_source = dict(metric_source) if metric_source else {}

    # ------------------------------------------------------------- discovery

    def supports(self, descriptor: PluginDescriptor) -> bool:
        return descriptor.plugin.provider == PROVIDER

    # ----------------------------------------------------------- observation

    def observe(
        self,
        descriptor: PluginDescriptor,
        requested: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> PluginState:
        """Build the per-run state from the allowlist plus requested values.

        A requested name that no descriptor entry declares is rejected: an
        experiment may not smuggle configuration past an allowlist it did not
        write (plan 10.1).
        """
        if not self.supports(descriptor):
            raise PluginAdapterError(
                f"plugin {descriptor.id}: adapter {self.adapter_id!r} does not handle "
                f"provider {descriptor.plugin.provider!r}"
            )

        values = observe_env(descriptor.benchmark.observed_env, environ)
        by_name = {value.name: value for value in values}

        wanted = dict(requested or {})
        unknown = sorted(set(wanted) - set(by_name))
        if unknown:
            raise PluginAdapterError(
                f"plugin {descriptor.id}: requested values are not allowlisted in the "
                "plugin descriptor: " + ", ".join(unknown)
            )

        merged = [
            value.model_copy(update={"requested_value": wanted[value.name]})
            if value.name in wanted
            else value
            for value in values
        ]
        enabled, note = self._enabled_state(descriptor, by_name)
        return PluginState(
            plugin_id=descriptor.id,
            plugin_version=descriptor.version,
            enabled=enabled,
            values=merged,
            verification_status=VerificationStatus.UNVERIFIED,
            events_observed=False,
            note=note,
        )

    # ---------------------------------------------------------------- verify

    def verify(self, descriptor: PluginDescriptor, state: PluginState) -> PluginState:
        """Verify against injected evidence only, and record how it was done.

        Without evidence the state stays ``unverified`` (or ``unsupported``
        when no reader could exist at all) and the note names the methods the
        descriptor declared, so a reader sees what is missing (plan 10.2).
        """
        effective = self._read_effective_config()
        if effective is None:
            return state.model_copy(
                update={
                    "verification_status": self._status_without_evidence(),
                    "note": _append_note(
                        state.note,
                        _no_evidence_note(descriptor.benchmark.verification.methods),
                    ),
                }
            )

        entries = {entry.name: entry for entry in descriptor.benchmark.observed_env}
        values, mismatches = _apply_effective(state.values, effective, entries)
        if mismatches:
            status = VerificationStatus.MISMATCH
            note = f"{_evidence_label()}: mismatch on " + ", ".join(mismatches)
        elif _verified_count(values):
            status = VerificationStatus.VERIFIED
            note = _evidence_label()
        else:
            status = VerificationStatus.UNVERIFIED
            note = (
                "effective configuration was read, but none of this run's values appear "
                "in it, so nothing could be confirmed"
            )
        return state.model_copy(
            update={"values": values, "verification_status": status, "note": note}
        )

    # --------------------------------------------------------------- metrics

    def normalize_metrics(
        self,
        descriptor: PluginDescriptor,
        state: PluginState,
    ) -> list[PluginMetric]:
        """Return every declared metric; measured only where evidence exists."""
        metrics: list[PluginMetric] = []
        for name in descriptor.benchmark.metrics:
            if name in self._metric_source:
                metrics.append(
                    PluginMetric(
                        name=name,
                        value=self._metric_source[name],
                        available=True,
                        source="injected metric source",
                    )
                )
            else:
                metrics.append(
                    PluginMetric(name=name, value=None, available=False, reason=NO_PLUGIN_METRICS)
                )
        return metrics

    # ---------------------------------------------------------------- report

    def report(
        self,
        descriptor: PluginDescriptor,
        digest: str | None = None,
        requested: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> PluginReport:
        """Observe, verify and normalize one plugin descriptor."""
        state = self.verify(descriptor, self.observe(descriptor, requested, environ))
        return PluginReport(
            plugin_id=descriptor.id,
            plugin_version=descriptor.version,
            digest=digest,
            enabled=state.enabled,
            state=state,
            metrics=self.normalize_metrics(descriptor, state),
            note=state.note,
        )

    # ---------------------------------------------------------------- private

    def _enabled_state(
        self,
        descriptor: PluginDescriptor,
        by_name: Mapping[str, ConfiguredValue],
    ) -> tuple[bool, str | None]:
        """``enabled`` comes only from a toggle the descriptor points at."""
        toggle = descriptor.benchmark.enabled_when
        if toggle is None:
            return False, (
                "descriptor declares no plugin-level toggle (benchmark.enabled_when), "
                "so activation is not observable and enabled is reported as false"
            )
        value = by_name.get(toggle)
        if value is None:
            return False, f"benchmark.enabled_when names an entry that is not allowlisted: {toggle}"
        if value.observed_value is None:
            return False, f"{toggle} is not set, so the plugin keeps its built-in default"
        return bool(value.observed_value), None

    def _read_effective_config(self) -> Mapping[str, Any] | None:
        if self._config_reader is None:
            return None
        try:
            return self._config_reader()
        except Exception:  # evidence that cannot be read is absent evidence
            return None

    def _status_without_evidence(self) -> VerificationStatus:
        """Without a reader a remote read is unsupported; a local one unverified."""
        return VerificationStatus.UNSUPPORTED


def _apply_effective(
    values: list[ConfiguredValue],
    effective: Mapping[str, Any],
    entries: Mapping[str, ObservedEnv],
) -> tuple[list[ConfiguredValue], list[str]]:
    """Compare requested values against the effective configuration.

    Only names present in the effective configuration are judged: a value the
    plugin does not report stays unverified instead of becoming a mismatch,
    because an absent key is not evidence of a difference. Sensitive entries
    record presence only — a secret is never copied out of the reader.
    """
    mismatches: list[str] = []
    updated: list[ConfiguredValue] = []
    for value in values:
        if value.name not in effective:
            updated.append(value)
            continue
        have = effective[value.name]
        entry = entries.get(value.name)
        secret = bool(entry is not None and entry.sensitive)
        updates: dict[str, Any] = {"verification_status": VerificationStatus.VERIFIED}
        if not secret:
            updates["effective_value"] = have
        updates["value_source"] = ValueSource.CONFIG_FILE
        if value.requested_value is not None and value.requested_value != have:
            updates["verification_status"] = VerificationStatus.MISMATCH
            mismatches.append(value.name)
        updated.append(value.model_copy(update=updates))
    return updated, mismatches


def _verified_count(values: list[ConfiguredValue]) -> int:
    return sum(1 for value in values if value.verification_status is VerificationStatus.VERIFIED)


def _evidence_label() -> str:
    return "verified against an injected effective-configuration reader"


def _no_evidence_note(methods: list[str]) -> str:
    if not methods:
        return "no verification method declared and no evidence source available"
    listed = ", ".join(methods)
    return (
        f"verification methods {listed} declared by the descriptor are unavailable on "
        "this instance: no effective-configuration reader was injected and the router "
        "refuses configuration reads"
    )


def _append_note(existing: str | None, addition: str) -> str:
    return f"{existing}; {addition}" if existing else addition
