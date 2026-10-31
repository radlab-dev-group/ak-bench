"""Status vocabularies shared by descriptors.

These exist so that "we did not check" and "the platform cannot do this" are
different values in every report (plan rules 9 and 25). The vocabulary matches
the capability evidence recorded in ``docs/AGENT_INTEGRATION.md``.
"""

from __future__ import annotations

from enum import StrEnum


class CapabilityStatus(StrEnum):
    """How well a declared capability is backed by evidence."""

    VERIFIED = "verified"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"

    @property
    def usable(self) -> bool:
        """Whether an experiment may rely on this capability.

        ``unverified`` is deliberately not usable: an unchecked capability must
        be confirmed before a plan depends on it.
        """
        return self in (CapabilityStatus.VERIFIED, CapabilityStatus.PARTIAL)


class VerificationStatus(StrEnum):
    """Verification state of a configuration value or component (plan 10.2)."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    MISMATCH = "mismatch"
    UNSUPPORTED = "unsupported"
    NOT_CONFIGURED = "not_configured"
    RUNTIME_ERROR = "runtime_error"

    @property
    def confirmed(self) -> bool:
        return self is VerificationStatus.VERIFIED


class ValueSource(StrEnum):
    """Where an observed value came from, so provenance is never lost."""

    REQUESTED = "requested"
    CONFIG_FILE = "config_file"
    ENVIRONMENT = "environment"
    API = "api"
    LOG = "log"
    INFERENCE = "inference"
    DEFAULT = "default"
    UNKNOWN = "unknown"


class SupportLevel(StrEnum):
    """Coarse support level for observability surfaces."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"
