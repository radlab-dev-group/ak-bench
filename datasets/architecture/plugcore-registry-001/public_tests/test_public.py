"""The registry, in miniature: register, look up, dispatch."""

from __future__ import annotations

from plugcore import apply
from plugcore.registry import PluginRegistry


def test_the_registry_registers_and_lists():
    registry = PluginRegistry()
    registry.register("shout", lambda text: text.upper() + "!")
    assert registry.get("shout")("hi") == "HI!"
    assert registry.names() == ["shout"]


def test_apply_still_works():
    assert apply("upper", "Ada") == "ADA"
    assert apply("reverse", "Ada") == "adA"
