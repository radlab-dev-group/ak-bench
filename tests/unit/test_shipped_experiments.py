"""Every shipped experiment YAML plans, and the interesting ones plan exactly.

The point of this file is that a new experiment cannot join the directory
without passing the same gate as the ones already in it: ``load_experiment_file``
and ``planner.plan()`` on each YAML, with no agent started and no router
contacted. Where the plan promises a number the acceptance criterion names,
that number is asserted here rather than read out of a terminal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from akbench.datasets import Dataset
from akbench.descriptors import load_registry
from akbench.evaluators.registry import default_registry
from akbench.experiments import ExperimentPlanner, load_experiment_file, parse_experiment

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS = REPO_ROOT / "configs" / "experiments"


def _experiment_files() -> list[Path]:
    return sorted(EXPERIMENTS.glob("*.yaml"))


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


def test_the_directory_holds_the_shipped_experiments() -> None:
    """A guard against the guard silently checking nothing."""
    names = {path.stem for path in _experiment_files()}
    assert {
        "wordcount-direct-sanity",
        "knowledge-on-off",
        "model-comparison",
        "full-matrix",
        "full-matrix-12",
        "auto-codex-on-off",
        "agent-comparison",
        "arena-roadmap-knowledge",
    } <= names


@pytest.mark.parametrize("path", _experiment_files(), ids=lambda item: item.stem)
def test_a_shipped_experiment_plans(planner: ExperimentPlanner, path: Path) -> None:
    loaded = load_experiment_file(path)
    plan = planner.plan(loaded)

    assert plan.ok, f"{loaded.identity}: {[issue.message for issue in plan.validation.errors]}"
    assert plan.counts.runs > 0
    assert plan.counts.runs <= loaded.descriptor.experiment.limits.max_runs
    assert plan.tasks, f"{loaded.identity} selects no task"
    assert plan.variants, f"{loaded.identity} expands to no variant"


@pytest.mark.parametrize("path", _experiment_files(), ids=lambda item: item.stem)
def test_a_shipped_experiment_declares_what_it_measures(path: Path) -> None:
    """An experiment that names no evaluator or metric cannot produce a verdict."""
    body = load_experiment_file(path).descriptor.experiment

    assert body.evaluation.evaluators, f"{path.stem} names no evaluator"
    assert body.metrics, f"{path.stem} names no metric"
    assert body.execution_policy.timeout_seconds, f"{path.stem} sets no run timeout"


def test_full_matrix_twelve_plans_exactly_twelve_configurations(
    planner: ExperimentPlanner,
) -> None:
    """The plan's example E: memory x routing x model, twelve configurations."""
    plan = planner.plan(load_experiment_file(EXPERIMENTS / "full-matrix-12.yaml"))

    assert plan.counts.variants == 12
    assert {
        (variant.values["knowledge_enabled"], variant.values["routing_heuristic_enabled"])
        for variant in plan.variants
    } == {(False, False), (False, True), (True, False), (True, True)}
    models = {variant.values["model"] for variant in plan.variants}
    assert models == {"qwen/Qwen3.8-27B", "qwen/Qwen3.8-Flash-Next", "auto_codex"}
    # Each configuration appears once, and one of them is the declared baseline.
    keys = [
        tuple(sorted((str(name), str(value)) for name, value in variant.values.items()))
        for variant in plan.variants
    ]
    assert len(set(keys)) == 12
    assert sum(1 for variant in plan.variants if variant.is_baseline) == 1


def test_auto_codex_on_off_varies_only_the_routing_toggles(
    planner: ExperimentPlanner,
) -> None:
    """The plan's example C: the routing plugin, alone, in four configurations."""
    loaded = load_experiment_file(EXPERIMENTS / "auto-codex-on-off.yaml")
    plan = planner.plan(loaded)

    assert plan.counts.variants == 4
    assert {factor.id for factor in plan.factors} == {
        "routing_heuristic_enabled",
        "routing_semantic_enabled",
    }
    # The model is pinned to the alias every arm asks for: without a trigger the
    # toggles would measure nothing at all.
    assert loaded.descriptor.experiment.agent.config["model"] == "auto_codex"


def test_an_experiment_may_declare_the_environment_of_the_instance_it_owns(
    planner: ExperimentPlanner,
) -> None:
    """The launch environment an experiment states applies to every arm."""
    plan = planner.plan(load_experiment_file(EXPERIMENTS / "auto-codex-on-off.yaml"))

    assert plan.runtime_env == {"LLM_ROUTER_UTILS_PLUGINS_PIPELINE": "agentic_routing_codex"}


def test_an_environment_declared_for_an_external_instance_is_refused(
    planner: ExperimentPlanner,
) -> None:
    """A shared instance is not started by this run, so nothing is set on it."""
    payload = load_experiment_file(EXPERIMENTS / "auto-codex-on-off.yaml").descriptor.model_dump()
    payload["experiment"]["execution"]["runtime"]["id"] = "llm-router-external"
    payload["experiment"]["execution"]["runtime"]["lifecycle"] = "external"

    report = planner.validate(parse_experiment(payload))

    assert "runtime_environment_needs_managed" in [issue.code for issue in report.errors]


def test_a_non_string_in_a_declared_launch_environment_is_refused() -> None:
    """An environment value is a string; a YAML boolean would be sent as ``True``."""
    from akbench.experiments.errors import ExperimentError

    payload = load_experiment_file(EXPERIMENTS / "auto-codex-on-off.yaml").descriptor.model_dump()
    payload["experiment"]["execution"]["runtime"]["env"] = {"SOMETHING": True}

    with pytest.raises(ExperimentError, match="valid string"):
        parse_experiment(payload)
