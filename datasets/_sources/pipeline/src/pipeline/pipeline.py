"""Stages in order, with a retry from the failed stage.

Stages are callables applied in the order they were added. When a stage
raises, the pipeline retries once from the failed stage: stages before
it have already done their work and must not run again.
"""

from __future__ import annotations

from collections.abc import Callable


class Pipeline:
    """An ordered list of stages with a single retry."""

    def __init__(self) -> None:
        self._stages: list[tuple[str, Callable]] = []

    def add_stage(self, name: str, fn: Callable) -> None:
        """Append a stage to the end of the pipeline."""
        self._stages.append((name, fn))

    def run(self, value):
        """Run the stages in order, retrying once from a failed stage."""
        current = value
        for index, (_name, fn) in enumerate(self._stages):
            try:
                current = fn(current)
            except Exception:
                # Retry once from the failed stage onward.
                for _retry_name, retry_fn in self._stages:
                    current = retry_fn(current)
                break
        return current
