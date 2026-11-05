"""Which plugins a run reports is a statement about that run.

A run that named no pipeline and set no toggle configured no plugin, so a row
about one would be noise: an ``unverified`` line for a plugin the process never
loaded reads as a defect that does not exist (the self-hosted model-only run
showed this). The filter keeps the rows that are real statements and drops the
rest, and it must not let a plugin of the installation masquerade as one of the
run.
"""

from __future__ import annotations

from akbench.cli.records import _plugins_the_run_configured
from akbench.descriptors.plugin import PluginDescriptor


def _descriptor(plugin_id: str, toggle: str | None) -> PluginDescriptor:
    observed_env: list[dict[str, object]] = [
        {"name": "SOME_INFRA_HOST", "type": "string", "observed": True},
    ]
    if toggle is not None:
        # enabled_when must name an allowlisted entry, so the toggle is one.
        observed_env.append({"name": toggle, "type": "boolean", "observed": True})
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "id": plugin_id,
        "version": "1.0.0",
        "title": plugin_id,
        "plugin": {"provider": "llm-router", "type": "knowledge"},
        "benchmark": {"observed_env": observed_env},
    }
    if toggle is not None:
        payload["benchmark"]["enabled_when"] = toggle  # type: ignore[index]
    return PluginDescriptor.model_validate(payload)


def _descriptors() -> list[PluginDescriptor]:
    return [
        _descriptor("agentic_knowledge", "LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED"),
        _descriptor("agentic_routing_codex", None),
    ]


def test_a_run_that_configured_nothing_reports_no_plugins() -> None:
    """The model-only self-hosted run: no pipeline, no toggle, no rows."""
    environment = {
        "LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_HOST": "http://192.168.100.70:8271",
        "LLM_ROUTER_KNOWLEDGE_AGENTIC_COLLECTION_PREFIX": "akbench_bench",
        "LLM_ROUTER_IN_DEBUG": "1",
    }
    assert _plugins_the_run_configured(_descriptors(), environment) == []
    assert _plugins_the_run_configured(_descriptors(), None) == []


def test_the_pipeline_names_the_plugins_the_process_loads() -> None:
    environment = {
        "LLM_ROUTER_UTILS_PLUGINS_PIPELINE": "agentic_routing_codex,agentic_knowledge",
    }
    selected = _plugins_the_run_configured(_descriptors(), environment)
    # the order is the descriptor registry's, not the pipeline's
    assert {descriptor.id for descriptor in selected} == {
        "agentic_routing_codex",
        "agentic_knowledge",
    }


def test_a_toggle_selects_a_plugin_the_pipeline_does_not_name() -> None:
    environment = {"LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED": "false"}
    selected = _plugins_the_run_configured(_descriptors(), environment)
    assert [descriptor.id for descriptor in selected] == ["agentic_knowledge"]


def test_infrastructure_environment_of_a_plugin_does_not_select_it() -> None:
    """Endpoints and prefixes are where a plugin talks to, not that it is on.

    The shipped managed descriptor carries the knowledge endpoints in its static
    env for every run; without a pipeline or a toggle that is not a statement
    about the knowledge plugin, and it must not pull the plugin into the record.
    """
    descriptors = _descriptors()
    environment = {
        "LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_HOST": "http://192.168.100.70:8271",
        "LLM_ROUTER_KNOWLEDGE_AGENTIC_KEY_PREFIX": "akbench-bench",
    }
    assert _plugins_the_run_configured(descriptors, environment) == []
