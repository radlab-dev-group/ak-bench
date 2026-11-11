"""A version of a synced file."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Version:
    """One version: its content, when it was written, and where from."""

    content: str
    updated_at: int
    origin: str
