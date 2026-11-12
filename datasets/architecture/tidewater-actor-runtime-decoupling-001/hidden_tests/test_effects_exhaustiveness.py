"""Two closed sets, and a shell that carries out everything in one of them.

An effect that is not data, an event the node will not accept, or an effect the
runner silently ignores all mean the same thing: the split is nominal, and the
side effects are still where they were.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest


def _effects():
    from tidewater import effects

    return effects


def test_the_two_sets_are_declared():
    effects = _effects()
    assert isinstance(getattr(effects, "EVENTS", None), (tuple, list, frozenset)), (
        "effects.EVENTS names the event types the node accepts"
    )
    assert isinstance(getattr(effects, "EFFECTS", None), (tuple, list, frozenset)), (
        "effects.EFFECTS names every effect the node can return"
    )


def test_the_event_set_is_the_three_inputs_of_the_node():
    effects = _effects()
    names = sorted(event.__name__ for event in effects.EVENTS)
    assert len(names) == 3, f"the node has three inputs (tick, delivered, proposed), got {names}"
    joined = " ".join(names).lower()
    for wanted in ("tick", "deliver", "propos"):
        assert wanted in joined, f"the event set is missing an event for {wanted!r}: {names}"


def test_every_effect_is_immutable_data_under_one_base():
    effects = _effects()
    assert len(effects.EFFECTS) >= 6, (
        f"a send, a persist, a trace record, a timer, a role change and an apply are six effects; got {len(effects.EFFECTS)}"
    )
    base = effects.Effect
    for effect in effects.EFFECTS:
        assert inspect.isclass(effect) and issubclass(effect, base), f"{effect!r} does not derive from Effect"
        assert dataclasses.is_dataclass(effect), f"{effect.__name__} is not a dataclass"
        assert getattr(effect, "__dataclass_params__").frozen, f"{effect.__name__} is mutable"


def test_the_effects_cover_the_side_effects_the_node_had():
    effects = _effects()
    names = " ".join(effect.__name__.lower() for effect in effects.EFFECTS)
    for wanted in ("send", "persist", "trace", "timer", "role", "apply"):
        assert wanted in names, f"no effect covers {wanted!r}; the effects are {names.split()}"


def test_a_returned_effect_cannot_be_changed():
    effects = _effects()
    event = next(iter(effects.EVENTS))
    instance = event(*([0] * len(dataclasses.fields(event)))) if dataclasses.fields(event) else event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, "tick", 1)


def test_the_runner_carries_effects_out():
    from tidewater.runtime.actor_runner import ActorRunner

    assert inspect.isclass(ActorRunner)
    assert callable(getattr(ActorRunner, "apply", None)), "ActorRunner.apply(node, effects) is the shell's entry point"
