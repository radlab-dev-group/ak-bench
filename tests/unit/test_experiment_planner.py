"""The experiment planner: validation (plan 12.1) and expansion (plan 12.2).

The shipped descriptors and the sample dataset are used on purpose: an
experiment plan is only as trustworthy as the registries behind it, so these
tests fail when a descriptor loses a fact the planner depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from akbench.datasets import Dataset
from akbench.descriptors import load_registry
from akbench.evaluators.registry import default_registry
from akbench.experiments import (
    ExperimentPlanner,
    ExperimentValidationError,
    parse_experiment,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS = REPO_ROOT / "configs" / "experiments"


@pytest.fixture(scope="module")
def planner() -> ExperimentPlanner:
    descriptors = load_registry(REPO_ROOT / "descriptors")
    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    return ExperimentPlanner(
        descriptors=descriptors,
        dataset=dataset,
        datasets_dir=REPO_ROOT / "datasets",
        implemented_evaluators={name for name, _ in default_registry().entries()},
    )


def document(name: str = "knowledge-on-off") -> dict:
    from akbench.experiments import load_experiment_file

    path = EXPERIMENTS / f"{name}.yaml"
    return load_experiment_file(path).descriptor.model_dump()


def experiment(payload: dict):
    return parse_experiment(payload)


def codes(report) -> list[str]:
    return [issue.code for issue in report.errors]


def warnings(report) -> list[str]:
    return [issue.code for issue in report.warnings]


# ------------------------------------------------------------------ planning


def test_the_shipped_experiments_all_plan(planner: ExperimentPlanner) -> None:
    from akbench.experiments import load_experiment_directory

    for loaded in load_experiment_directory(EXPERIMENTS):
        plan = planner.plan(loaded)
        assert plan.ok, f"{loaded.identity}: {[i.message for i in plan.validation.errors]}"
        assert plan.counts.runs > 0


def test_plan_counts_are_the_product_of_the_axes(planner: ExperimentPlanner) -> None:
    plan = planner.plan(experiment(document("full-matrix")))

    counts = plan.counts
    assert counts.variants == 4, "knowledge on/off x two models"
    assert counts.repetitions == 3
    assert counts.tasks == 1
    assert counts.runs == counts.tasks * counts.variants * counts.repetitions == 12


def test_variant_ids_are_stable_and_distinct(planner: ExperimentPlanner) -> None:
    first = planner.plan(experiment(document("full-matrix")))
    second = planner.plan(experiment(document("full-matrix")))

    assert [v.variant_id for v in first.variants] == [v.variant_id for v in second.variants]
    assert len({v.variant_id for v in first.variants}) == len(first.variants)


def test_a_model_factor_becomes_an_agent_parameter(planner: ExperimentPlanner) -> None:
    plan = planner.plan(experiment(document("model-comparison")))

    for variant in plan.variants:
        assert variant.agent_config["model"] == variant.values["model"]
        assert variant.environment_requests == {}


def test_a_plugin_factor_becomes_an_environment_request(planner: ExperimentPlanner) -> None:
    plan = planner.plan(experiment(document("knowledge-on-off")))

    for variant in plan.variants:
        assert "knowledge_enabled" not in variant.agent_config, (
            "knowledge is configured on the runtime, not on the agent"
        )
        assert "knowledge_enabled" in variant.environment_requests
        assert "env" in variant.applies["knowledge_enabled"]


def test_one_factor_at_a_time_produces_a_reference_variant(planner: ExperimentPlanner) -> None:
    plan = planner.plan(experiment(document("model-comparison")))

    baselines = [variant for variant in plan.variants if variant.is_baseline]
    assert len(baselines) == 1
    assert baselines[0].values == {"model": "qwen/Qwen3.8-27B"}


def test_the_plan_pins_the_descriptors_it_used(planner: ExperimentPlanner) -> None:
    plan = planner.plan(experiment(document("knowledge-on-off")))

    snapshots = plan.descriptor_snapshots
    assert any(key.startswith("agent:codex@") for key in snapshots)
    assert any(key.startswith("runtime:llm-router-ak-bench@") for key in snapshots)
    assert any(key.startswith("dimension:knowledge_enabled@") for key in snapshots)
    assert all(value.startswith("sha256:") for value in snapshots.values())


def test_the_estimate_comes_from_the_declared_timeout(planner: ExperimentPlanner) -> None:
    plan = planner.plan(experiment(document("knowledge-on-off")))

    assert plan.estimate.run_seconds_upper_bound == 900
    assert plan.estimate.total_seconds_upper_bound == 900 * plan.counts.runs


# ---------------------------------------------------------------- validation


def test_an_environment_is_validated_and_pinned(planner: ExperimentPlanner) -> None:
    """An experiment may name where its runs execute; the plan pins that choice."""
    payload = document("wordcount-direct-sanity")
    payload["experiment"]["environment"] = {"id": "local-host"}

    plan = planner.plan(experiment(payload))

    assert plan.ok
    pinned = [key for key in plan.descriptor_snapshots if key.startswith("environment:local-host@")]
    assert pinned, plan.descriptor_snapshots
    assert plan.descriptor_snapshots[pinned[0]].startswith("sha256:")


def test_an_unknown_environment_blocks_the_plan(planner: ExperimentPlanner) -> None:
    payload = document("wordcount-direct-sanity")
    payload["experiment"]["environment"] = {"id": "no-such-environment"}

    report = planner.validate(experiment(payload))

    assert "environment_unknown" in codes(report)


def test_a_docker_environment_is_refused_until_the_sandbox_exists(
    planner: ExperimentPlanner,
) -> None:
    """Plan 14's container sandbox is not implemented (phase B), so saying so beats lying.

    A run that asked for a container and quietly got the host would record an
    isolation it never had, which is the kind of gap plan rule 11 exists to
    keep out of a result.
    """
    payload = document("wordcount-direct-sanity")
    payload["experiment"]["environment"] = {"id": "docker-python312"}

    report = planner.validate(experiment(payload))

    assert "environment_sandbox_unavailable" in codes(report)


def test_the_shipped_environments_are_consistent(planner: ExperimentPlanner) -> None:
    """The environment directory ships a host environment the plan can use today."""
    from akbench.descriptors import DescriptorKind

    entries = planner.descriptors.entries(DescriptorKind.ENVIRONMENT)
    by_id = {entry.snapshot.id: entry.descriptor for entry in entries}

    assert "local-host" in by_id
    assert by_id["local-host"].environment.sandbox.value == "host"
    assert by_id["local-host"].environment.image is None
    # The docker one states its image: a manifest that names a container has
    # to say which one, and an environment without it cannot be built.
    docker = by_id["docker-python312"]
    assert docker.environment.sandbox.value == "docker"
    assert docker.environment.image


def test_the_concurrency_of_a_policy_is_a_warning_in_the_plan(
    planner: ExperimentPlanner,
) -> None:
    """Running cells at once shares the machine; the plan says so before it runs."""
    payload = document("wordcount-direct-sanity")
    payload["experiment"]["execution_policy"]["concurrency"] = 4

    report = planner.validate(experiment(payload))

    assert "concurrency_above_one" in warnings(report)
    assert report.ok


def test_a_serial_plan_carries_no_concurrency_warning(planner: ExperimentPlanner) -> None:
    payload = document("wordcount-direct-sanity")

    report = planner.validate(experiment(payload))

    assert "concurrency_above_one" not in warnings(report)


def test_an_unknown_agent_blocks_the_plan(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["agent"] = {"id": "no-such-agent"}

    report = planner.validate(experiment(payload))

    assert "agent_unknown" in codes(report)


def test_an_uncontrollable_dimension_cannot_be_a_factor(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["factors"] = {"dimensions": [{"id": "routed_model"}]}

    report = planner.validate(experiment(payload))

    assert "factor_unusable" in codes(report)
    assert "not controllable" in report.errors[0].message


def test_a_factor_value_outside_the_dimension_is_refused(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["factors"] = {
        "dimensions": [{"id": "knowledge_enabled", "values": ["sometimes"]}]
    }

    report = planner.validate(experiment(payload))

    assert "factor_unusable" in codes(report)


def test_a_plugin_factor_needs_a_runtime(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["execution"] = {"mode": "direct"}

    report = planner.validate(experiment(payload))

    assert "plugin_factor_without_runtime" in codes(report)


def test_an_external_router_cannot_control_a_plugin_per_run(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["execution"]["runtime"] = {
        "id": "llm-router-external",
        "lifecycle": "external",
    }

    report = planner.validate(experiment(payload))

    assert "per_run_plugin_control_unsupported" in codes(report)


def test_a_plugin_factor_validates_cleanly_on_the_self_start_runtime(
    planner: ExperimentPlanner,
) -> None:
    """No caveat is owed when the value goes into the process the run launched.

    The self-start instance declares per-run plugin control as verified — the
    toggle is in the environment the run started — so the plan carries no
    refusal and no "verified by construction" warning; the remaining doubt is
    the plugin's own accounting, recorded per run, not a plan-level caveat.
    The shared instance, which cannot be told, is covered by the refusal test.
    """
    report = planner.validate(experiment(document()))

    assert report.ok
    assert "per_run_plugin_control_unsupported" not in codes(report)
    assert "plugin_factor_verified_by_construction" not in warnings(report)


def test_an_unknown_runtime_blocks_the_plan(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["execution"]["runtime"] = {"id": "llm-router-mk2"}

    report = planner.validate(experiment(payload))

    assert "runtime_unknown" in codes(report)


def test_an_empty_dataset_selection_blocks_the_plan(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["dataset"]["filters"] = {"task_ids": ["no-such-task"]}

    report = planner.validate(experiment(payload))

    assert "dataset_selection_empty" in codes(report)


def test_an_unknown_evaluator_blocks_the_plan(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["evaluation"] = {"evaluators": ["no_such_evaluator"]}

    report = planner.validate(experiment(payload))

    assert "evaluator_undeclared" in codes(report)


def test_an_unknown_metric_blocks_the_plan(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["metrics"] = ["no_such_metric"]

    report = planner.validate(experiment(payload))

    assert "metric_undeclared" in codes(report)


def test_an_uncomputable_metric_is_a_warning_not_a_zero(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["metrics"] = ["total_cost"]

    report = planner.validate(experiment(payload))

    assert report.ok
    assert "metric_unavailable" in warnings(report)


def test_declared_limits_stop_an_expensive_plan(planner: ExperimentPlanner) -> None:
    payload = document("full-matrix")
    payload["experiment"]["limits"] = {"max_runs": 4}

    report = planner.validate(experiment(payload))

    assert codes(report) == ["limit_runs"]


def test_a_comparison_type_without_its_factor_is_refused(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["type"] = "model_comparison"

    report = planner.validate(experiment(payload))

    assert "comparison_without_factor" in codes(report)


def test_a_static_config_cannot_fight_a_factor(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["agent"]["config"] = {"model": "auto_codex"}
    payload["experiment"]["factors"] = {"dimensions": [{"id": "model"}]}

    report = planner.validate(experiment(payload))

    assert "factor_config_conflict" in codes(report)


def test_a_missing_baseline_is_reported_as_a_gap(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["factors"].pop("baseline", None)

    report = planner.validate(experiment(payload))

    assert "baseline_undeclared" in warnings(report)


def test_a_baseline_outside_the_matrix_blocks_the_plan(planner: ExperimentPlanner) -> None:
    """A baseline the matrix cannot produce would leave the comparison without a reference."""
    payload = document("model-comparison")
    payload["experiment"]["factors"]["dimensions"] = [
        {"id": "model", "values": ["qwen/Qwen3.8-27B"]}
    ]
    payload["experiment"]["factors"]["baseline"] = {"model": "auto_codex"}

    report = planner.validate(experiment(payload))

    assert "baseline_value_invalid" in codes(report)
    assert "baseline_not_in_matrix" in codes(report)


def test_a_one_factor_experiment_without_a_baseline_is_refused(planner: ExperimentPlanner) -> None:
    payload = document("model-comparison")
    payload["experiment"]["factors"].pop("baseline")

    report = planner.validate(experiment(payload))

    assert "baseline_missing" in codes(report)


def test_an_undeclared_timeout_leaves_the_cost_unbounded(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["execution_policy"].pop("timeout_seconds", None)

    report = planner.validate(experiment(payload))

    assert "timeout_undeclared" in warnings(report)


def test_planning_refuses_an_unrunnable_experiment(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["agent"] = {"id": "no-such-agent"}

    with pytest.raises(ExperimentValidationError) as excinfo:
        planner.plan(experiment(payload))

    assert "agent_unknown" in str(excinfo.value)
    assert excinfo.value.details["issues"]


def test_requiring_an_unusable_capability_blocks_the_plan(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["required_capabilities"] = ["cost_usage"]

    report = planner.validate(experiment(payload))

    assert "capability_unavailable" in codes(report)


def test_the_descriptor_kind_of_a_plan_survives_round_trip(planner: ExperimentPlanner) -> None:
    loaded = experiment(document("full-matrix"))
    plan = planner.plan(loaded)

    assert plan.experiment.digest.startswith("sha256:")
    assert plan.summary()["strategy"] == "custom_matrix"
    assert plan.as_dict()["counts"]["runs"] == 12


def test_dimension_registry_rejects_an_unknown_id(planner: ExperimentPlanner) -> None:
    from akbench.experiments.dimensions import DimensionResolutionError

    with pytest.raises(DimensionResolutionError, match="unknown dimension"):
        planner.dimensions.factor("no_such_dimension")


def test_task_timeout_exceeding_experiment_timeout_is_refused(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["execution_policy"]["timeout_seconds"] = 10

    report = planner.validate(experiment(payload))

    assert "task_timeout_exceeds_experiment" in codes(report)
    with pytest.raises(ExperimentValidationError) as excinfo:
        planner.plan(experiment(payload))
    assert "task_timeout_exceeds_experiment" in str(excinfo.value)


def test_task_timeout_within_experiment_timeout_is_accepted(planner: ExperimentPlanner) -> None:
    payload = document()
    payload["experiment"]["execution_policy"]["timeout_seconds"] = 3600

    report = planner.validate(experiment(payload))

    assert "task_timeout_exceeds_experiment" not in codes(report)


# ------------------------------------------------------- runtime_env binding


def test_a_combination_env_reaches_its_variant(planner: ExperimentPlanner) -> None:
    """The arm that wants a plugin names it where the arm is declared."""
    plan = planner.plan(experiment(document("router-config-comparison")))

    by_values = {
        (v.values.get("model"), v.values.get("knowledge_enabled")): v
        for v in plan.variants
    }
    baseline = by_values[("qwen/Qwen3.8-27B", False)]
    knowledge = by_values[("auto_codex", True)]
    pipeline = "LLM_ROUTER_UTILS_PLUGINS_PIPELINE"
    assert baseline.runtime_env == {pipeline: "agentic_routing_codex"}
    assert knowledge.runtime_env == {
        pipeline: "agentic_routing_codex,agentic_knowledge"
    }


def test_the_shipped_selfhost_experiment_keeps_its_pipeline_out_of_the_runtime(
    planner: ExperimentPlanner,
) -> None:
    """A pipeline in the runtime descriptor would load its plugins in every arm.

    The regression this guards: the first version of the self-hosted run loaded
    the knowledge plugin in the arm that measured the router without it, because
    the pipeline sat in the runtime's static environment. Which plugins an arm
    loads is always declared under its own ``runtime_env`` — an arm that wants
    no plugin leaves the pipeline out, an arm that measures knowledge names the
    knowledge plugin — so the difference between arms is a fact about the
    processes they started, not about the runtime.
    """
    from akbench.descriptors import DescriptorKind, load_registry

    registry = load_registry(REPO_ROOT / "descriptors")
    entry = registry.get(DescriptorKind.RUNTIME, "llm-router-ak-bench")
    assert entry is not None
    assert "LLM_ROUTER_UTILS_PLUGINS_PIPELINE" not in entry.descriptor.runtime.managed.env

    from akbench.experiments import load_experiment_file

    loaded = load_experiment_file(EXPERIMENTS / "llm-router-selfhost-fast.yaml")
    plan = planner.plan(loaded)
    pipelines = [
        (variant.values, variant.runtime_env.get("LLM_ROUTER_UTILS_PLUGINS_PIPELINE"))
        for variant in plan.variants
    ]
    # every arm that names the knowledge plugin is the knowledge arm; no other
    # arm may load it, and the runtime descriptor names none.
    for values, pipeline in pipelines:
        if "agentic_knowledge" in (pipeline or ""):
            assert values.get("model") == "auto_codex"


def test_the_shipped_managed_runtime_declares_the_knowledge_connections() -> None:
    """A knowledge arm whose plugin reaches neither store measures nothing.

    The plugin reads its Redis settings from its own prefix and never from
    ``LLM_ROUTER_REDIS_*``, and a RESP3 handshake against the Redis here is
    answered with ``unknown command HELLO`` — after which every command fails
    and the layer fails open, silently. The connection is therefore part of the
    runtime descriptor rather than something the operator remembers to export,
    with one exception: a credential is never a descriptor's content, so the
    engine's password stays in the operator's environment.
    """
    from akbench.descriptors import DescriptorKind, load_registry

    registry = load_registry(REPO_ROOT / "descriptors")
    runtime = registry.get(DescriptorKind.RUNTIME, "llm-router-ak-bench")
    plugin = registry.get(DescriptorKind.PLUGIN, "agentic_knowledge")
    assert runtime is not None and plugin is not None
    env = runtime.descriptor.runtime.managed.env

    assert env["LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_HOST"] == env["LLM_ROUTER_REDIS_HOST"]
    assert env["LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_PROTOCOL"] == "2"
    assert env["LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_HOST"].startswith("http")
    assert env["LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_USERNAME"]
    assert env["LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_PASSWORD"]

    # An unallowlisted name is an invisible one: what the plugin descriptor
    # does not declare cannot be observed, verified or shown in a report.
    allowlisted = {entry.name for entry in plugin.descriptor.benchmark.observed_env}
    declared = {
        name
        for name in env
        if name.startswith("LLM_ROUTER_KNOWLEDGE_AGENTIC_")
    }
    assert declared <= allowlisted, sorted(declared - allowlisted)


def test_a_variant_env_is_part_of_the_variant_identity(planner: ExperimentPlanner) -> None:
    """Two arms that differ only in their runtime env are two configurations."""
    payload = document("knowledge-on-off")
    payload["experiment"]["execution"] = {
        "mode": "router",
        "runtime": {"id": "llm-router-ak-bench", "lifecycle": "managed"},
    }
    payload["experiment"]["factors"] = {
        "strategy": "custom_matrix",
        "dimensions": [{"id": "knowledge_enabled"}],
        "baseline": {"knowledge_enabled": False},
        "combinations": [
            {"knowledge_enabled": False, "runtime_env": {"PIPE": "routing"}},
            {"knowledge_enabled": True, "runtime_env": {"PIPE": "routing,knowledge"}},
        ],
    }

    plan = planner.plan(experiment(payload))

    ids = [variant.variant_id for variant in plan.variants]
    assert len(ids) == 2 and len(set(ids)) == 2
    envs = {v.values["knowledge_enabled"]: v.runtime_env for v in plan.variants}
    assert envs[False] == {"PIPE": "routing"}
    assert envs[True] == {"PIPE": "routing,knowledge"}


def test_a_combination_env_against_an_external_runtime_is_refused(
    planner: ExperimentPlanner,
) -> None:
    payload = document("knowledge-on-off")
    payload["experiment"]["execution"] = {
        "mode": "router",
        "runtime": {"id": "llm-router-external"},
    }
    payload["experiment"]["factors"] = {
        "strategy": "custom_matrix",
        "dimensions": [{"id": "knowledge_enabled"}],
        "combinations": [
            {"knowledge_enabled": True, "runtime_env": {"PIPE": "routing,knowledge"}}
        ],
    }

    report = planner.validate(experiment(payload))

    assert "runtime_environment_needs_managed" in codes(report)


def test_the_shipped_atlas_memory_experiment_declares_its_six_arms(
    planner: ExperimentPlanner,
) -> None:
    """Three models × the knowledge plugin in or out of the process, and nothing else.

    The memory effect is measured once per routing decision, so every model has
    to appear twice: an experiment that only runs the fixed models with memory
    has no fixed-model control, and one that only runs the alias without memory
    has no control for routing. The pipelines are the part that rots quietly: an
    arm that says `knowledge_enabled: false` while loading the knowledge plugin
    is an off arm that reads, and an arm that drops the routing plugin does not
    route at all — which is why only the alias arms load it: a fixed model asks
    for one model by name and has nothing to route.
    """

    from akbench.experiments import load_experiment_file

    plan = planner.plan(
        load_experiment_file(EXPERIMENTS / "knowledge-replay-atlas.yaml")
    )
    pipeline = "LLM_ROUTER_UTILS_PLUGINS_PIPELINE"
    arms = {(v.values["model"], v.values["knowledge_enabled"]): v for v in plan.variants}
    assert sorted(arms) == [
        ("auto_codex", False),
        ("auto_codex", True),
        ("qwen/Qwen3.8-27B", False),
        ("qwen/Qwen3.8-27B", True),
        ("qwen/Qwen3.8-Flash-Next", False),
        ("qwen/Qwen3.8-Flash-Next", True),
    ]
    for (model, enabled), variant in arms.items():
        declared = variant.runtime_env.get(pipeline, "")
        assert ("agentic_knowledge" in declared) is enabled, (model, enabled, declared)
        assert ("agentic_routing_codex" in declared) is (model == "auto_codex"), (
            model,
            enabled,
            declared,
        )
    # The reference is a fixed model with no memory, and no plugin of any kind.
    baseline = next(variant for variant in plan.variants if variant.is_baseline)
    assert baseline.values == {"model": "qwen/Qwen3.8-27B", "knowledge_enabled": False}
    assert baseline.runtime_env.get(pipeline) is None
    # 1 task x 6 configurations, one repetition each.
    assert plan.counts.runs == 6


def test_the_shipped_memory_suite_switches_the_plugin_mechanisms_on_per_arm(
    planner: ExperimentPlanner,
) -> None:
    """The memory suite measures mechanisms the plugins ship switched off.

    Loop escalation, the compaction archive, the documentation map and the
    routing plugin's session memory are off by default; an arm that claims to
    measure them must declare them on the process it starts, and the ablation
    arm that keeps the knowledge plugin while turning them off must say so
    just as explicitly, or the two arms would differ in nothing the record
    can show.
    """

    from akbench.experiments import load_experiment_file

    plan = planner.plan(
        load_experiment_file(EXPERIMENTS / "knowledge-replay-memory-suite.yaml")
    )
    pipeline = "LLM_ROUTER_UTILS_PLUGINS_PIPELINE"
    prefix = "LLM_ROUTER_KNOWLEDGE_AGENTIC_"
    arms = {
        (
            v.values["model"],
            v.values["knowledge_enabled"],
            v.values["knowledge_escalation_enabled"],
        ): v
        for v in plan.variants
    }
    assert sorted(arms) == [
        ("auto_codex", False, False),
        ("auto_codex", True, False),
        ("auto_codex", True, True),
        ("qwen/Qwen3.8-27B", False, False),
        ("qwen/Qwen3.8-27B", True, False),
        ("qwen/Qwen3.8-Flash-Next", False, False),
        ("qwen/Qwen3.8-Flash-Next", True, False),
    ]
    for (model, enabled, escalation), variant in arms.items():
        declared = variant.runtime_env.get(pipeline, "")
        assert ("agentic_knowledge" in declared) is enabled, (model, declared)
        assert ("agentic_routing_codex" in declared) is (model == "auto_codex"), (
            model,
            declared,
        )
        if escalation:
            # The full configuration: every mechanism declared on.
            for name in ("ARCHIVE_ENABLED", "DOCS_ENABLED", "DOCS_CONTEXT_ENABLED"):
                assert variant.runtime_env[prefix + name] == "true", name
            assert variant.runtime_env[prefix + "LOOP_THRESHOLD"] == "3"
            assert (
                variant.runtime_env["LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_ENABLED"]
                == "true"
            )
    # The ablation keeps the plugin and switches the mechanisms beyond recipes off.
    ablation = arms[("auto_codex", True, False)]
    for name in ("ARCHIVE_ENABLED", "DOCS_ENABLED", "DOCS_CONTEXT_ENABLED"):
        assert ablation.runtime_env[prefix + name] == "false", name
    # The documentation budget is raised above the atlas incident corpus.
    full = arms[("auto_codex", True, True)]
    assert int(full.runtime_env[prefix + "DOCS_MAX_FILES"]) > 400
    baseline = next(variant for variant in plan.variants if variant.is_baseline)
    assert baseline.values == {
        "model": "qwen/Qwen3.8-27B",
        "knowledge_enabled": False,
        "knowledge_escalation_enabled": False,
    }
    # 13 tasks of the suite x 7 configurations, one repetition each.
    assert plan.counts.runs == 91


# ------------------------------------------------------- agent comparison


def _comparison(values: list[str]) -> dict:
    """The shipped comparison, with the agent factor rewritten to ``values``."""
    payload = document("agent-comparison")
    dimensions = payload["experiment"]["factors"]["dimensions"]
    assert [item["id"] for item in dimensions] == ["agent"]
    dimensions[0]["values"] = values
    return payload


def test_an_agent_comparison_expands_one_variant_per_agent(
    planner: ExperimentPlanner,
) -> None:
    """The agent is a factor like any other, so each arm gets its own variant."""
    plan = planner.plan(experiment(_comparison(["codex", "fake"])))

    assert plan.ok
    assert [variant.agent_id for variant in plan.variants] == ["codex", "fake"]
    assert len({variant.config_hash for variant in plan.variants}) == 2
    assert plan.counts.variants == 2


def test_an_agent_comparison_marks_the_capability_differences(
    planner: ExperimentPlanner,
) -> None:
    """What the arms cannot do stays visible instead of becoming a zero."""
    report = planner.validate(experiment(_comparison(["codex", "fake"])))

    differences = [issue for issue in report.warnings if issue.code == "agent_capability_difference"]
    assert len(differences) == 1
    assert "codex vs fake" in differences[0].message
    assert differences[0].context["agents"] == ["codex", "fake"]
    # Only names both descriptors speak about are compared, so the reported set
    # is exactly the shared names whose status differs between the two.
    from akbench.descriptors import load_registry

    registry = load_registry(REPO_ROOT / "descriptors")
    codex = next(
        entry.descriptor for entry in registry.entries() if getattr(entry.descriptor, "id", None) == "codex"
    )
    fake = next(
        entry.descriptor for entry in registry.entries() if getattr(entry.descriptor, "id", None) == "fake"
    )
    shared = set(codex.agent.capabilities) & set(fake.agent.capabilities)
    expected = {
        name: [codex.agent.capabilities[name].value, fake.agent.capabilities[name].value]
        for name in shared
        if codex.agent.capabilities[name] is not fake.agent.capabilities[name]
    }
    assert differences[0].context["differences"] == expected
    assert expected["timeout_control"] == ["unsupported", "verified"]


def test_an_arm_without_a_descriptor_is_refused(tmp_path: Path) -> None:
    """An arm the dimension allows but no descriptor describes is refused."""
    import shutil

    from akbench.experiments import parse_experiment

    tree = tmp_path / "descriptors"
    shutil.copytree(REPO_ROOT / "descriptors", tree)
    (tree / "agents" / "http.yaml").unlink()
    descriptors = load_registry(tree)
    dataset = Dataset.load(REPO_ROOT / "datasets", base_dir=REPO_ROOT)
    comparison = ExperimentPlanner(
        descriptors=descriptors,
        dataset=dataset,
        datasets_dir=REPO_ROOT / "datasets",
        implemented_evaluators={name for name, _ in default_registry().entries()},
    )
    report = comparison.validate(parse_experiment(_comparison(["codex", "http"])))

    assert "agent_unknown" in codes(report)


def test_a_single_arm_agent_comparison_warns(planner: ExperimentPlanner) -> None:
    """An experiment that names itself a comparison but has one arm says so."""
    payload = _comparison(["codex"])
    plan = planner.plan(experiment(payload))

    assert plan.ok
    assert "agent_comparison_single_arm" in warnings(plan.validation)


def test_an_agent_comparison_sends_no_configuration_to_either_arm(
    planner: ExperimentPlanner,
) -> None:
    """A parameter belongs to an agent, so a shared arm configuration is empty."""
    plan = planner.plan(experiment(_comparison(["codex", "fake"])))

    assert all(variant.agent_config == {} for variant in plan.variants)
