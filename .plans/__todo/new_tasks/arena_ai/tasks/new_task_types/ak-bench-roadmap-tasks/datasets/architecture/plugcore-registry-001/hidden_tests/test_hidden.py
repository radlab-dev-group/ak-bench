"""The registry, proven: target module plus preserved behaviour.

These tests fail on the base commit (the target module does not exist)
and pass once the dispatch is a registry.
"""

from __future__ import annotations

import pytest

from plugcore import apply
from plugcore.registry import PluginRegistry


def test_the_registry_registers_looks_up_and_lists():
    registry = PluginRegistry()
    registry.register("shout", lambda text: text.upper() + "!")
    registry.register("twice", lambda text: text + text)
    assert registry.get("shout")("hi") == "HI!"
    assert registry.get("twice")("ab") == "abab"
    assert registry.names() == ["shout", "twice"]


def test_get_refuses_an_unknown_name():
    registry = PluginRegistry()
    with pytest.raises(ValueError):
        registry.get("nope")


def test_a_new_transform_works_through_apply():
    from plugcore import registry as registry_module

    registry_module.register("shout", lambda text: text.upper() + "!")
    assert apply("shout", "hi") == "HI!"


def test_the_builtins_behaviour_is_unchanged():
    assert apply("upper", "Ada") == "ADA"
    assert apply("lower", "Ada") == "ada"
    assert apply("reverse", "Ada") == "adA"
    with pytest.raises(ValueError):
        apply("nope", "Ada")
