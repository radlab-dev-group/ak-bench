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
    the pipeline sat in the runtime's static environment. An arm that wants a
    plugin names it under its own ``runtime_env``; an arm that does not leave
    the pipeline out, so its process loads no plugins at all.
    """
    from akbench.descriptors import DescriptorKind, load_registry

    registry = load_registry(REPO_ROOT / "descriptors")
    entry = registry.get(DescriptorKind.RUNTIME, "llm-router-ak-bench")
    assert entry is not None
    assert "LLM_ROUTER_UTILS_PLUGINS_PIPELINE" not in entry.descriptor.runtime.managed.env

    from akbench.experiments import load_experiment_file

    loaded = load_experiment_file(EXPERIMENTS / "llm-router-selfhost-fast.yaml")
    plan = planner.plan(loaded)
    for variant in plan.variants:
        pipeline = variant.runtime_env.get("LLM_ROUTER_UTILS_PLUGINS_PIPELINE")
        if pipeline is not None:
            assert "agentic_knowledge" not in pipeline.split(","), (
                "an arm that does not measure knowledge loads no knowledge plugin"
            )


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
