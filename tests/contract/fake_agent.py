"""The reference adapter, re-exported from its home in the source tree.

The implementation moved from this test helper to
``src/akbench/agents/fake.py`` (plan 6.5, F1) so that an experiment can name
the agent ``fake`` like any other registered agent. This module keeps the old
import path working for the contract suite and the unit tests.
"""

from akbench.agents.fake import (
    ADAPTER_ID,
    BEHAVIOURS,
    FakeAdapter,
    FakeOptions,
    FakeProfile,
    resolve_behaviour,
)

__all__ = [
    "ADAPTER_ID",
    "BEHAVIOURS",
    "FakeAdapter",
    "FakeOptions",
    "FakeProfile",
    "resolve_behaviour",
]
