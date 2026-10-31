"""Plugin configuration and observability (plan section 10 and 26, phase 9).

A plugin adapter is the only component allowed to read, write, verify and
interpret a concrete plugin: the experiment engine sees plugin state and
metrics through the contract in :mod:`akbench.plugins.contract`, never the
plugin's own environment variables or endpoints (plan rule 10.3).

Every value stays honest about its provenance: presence in the environment or
in a configuration file is *not* proof the plugin works, so state is reported
as requested/configured/effective/observed with a verification status, and a
metric with no source is ``unavailable`` rather than zero (plan section 18).
"""

from akbench.plugins.adapter import LlmRouterPluginAdapter
from akbench.plugins.contract import PluginAdapter, PluginAdapterError, PluginReport
from akbench.plugins.registry import PluginRegistry, build_plugin_registry

__all__ = [
    "LlmRouterPluginAdapter",
    "PluginAdapter",
    "PluginAdapterError",
    "PluginRegistry",
    "PluginReport",
    "build_plugin_registry",
]
