"""Base descriptor model shared by all extensible components.

Every descriptor is versioned by ``schema_version``, ``id`` and ``version`` so
that a change to a descriptor cannot silently reinterpret historical results.
Snapshots are written into the experiment record (plan section 9).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DescriptorBase(_StrictModel):
    """Common identity and versioning fields for all descriptors."""

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Version of the descriptor schema itself.",
    )
    id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$",
        description=(
            "Stable, unique identifier within its registry. '/' and ':' are allowed "
            "because model ids use them (qwen/Qwen3.8-Flash-Next, qwen3-coder:30b)."
        ),
    )
    version: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Version of this specific descriptor instance.",
    )
    title: str | None = Field(
        default=None,
        max_length=255,
        description="Human-readable title.",
    )
    description: str | None = Field(
        default=None,
        description="Free-form description.",
    )

    @field_validator("schema_version")
    @classmethod
    def _check_schema(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {value!r}, expected {SCHEMA_VERSION!r}"
            )
        return value

    def identity(self) -> str:
        """Return a stable ``id@version`` string for cross-references."""
        return f"{self.id}@{self.version}"

    def to_snapshot(self) -> dict[str, Any]:
        """Return a plain dict suitable for embedding in an experiment snapshot."""
        return self.model_dump(mode="json")
