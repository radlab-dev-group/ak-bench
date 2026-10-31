"""Screening an export for material that must not leave the machine.

A run record contains agent output, and agent output can contain anything the
agent saw: a token printed by a debug command, a key in a config file, a
bearer header in a trace. The export therefore screens every string before it
is written, and it does so conservatively — a match is replaced, not printed.

The replacement names the kind of what was withheld
(``[REDACTED:openai-key]``) and the count is reported, so a reader can tell
that something was removed without learning what it was. Nothing is masked in
place: a partially-shown secret is still a secret.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

REDACTION = "[REDACTED:{kind}]"

#: Environment names whose value must never appear in an export.
SECRET_ENVIRONMENT_NAMES: frozenset[str] = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "LLM_ROUTER_API_KEY",
        "ROUTER_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "GITHUB_TOKEN",
        "GITLAB_TOKEN",
        "HF_TOKEN",
    }
)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pem-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "authorization-header",
        re.compile(r"(?i)\bauthorization\b\s*[:=]\s*\S+"),
    ),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    (
        "generic-key",
        re.compile(r"(?i)\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)\b\s*[:=]\s*\S+"),
    ),
    ("long-hex", re.compile(r"\b[0-9a-fA-F]{40,}\b")),
)


@dataclass
class Redactor:
    """Counts what it removed while rewriting text and structures."""

    counts: dict[str, int] = field(default_factory=dict)
    environment_values: dict[str, str] = field(default_factory=dict)

    def note(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def text(self, value: str) -> str:
        """Replace every match in one string, counting the kinds it removed."""
        result = value
        for kind, pattern in _PATTERNS:
            result, hits = pattern.subn(REDACTION.format(kind=kind), result)
            for _ in range(hits):
                self.note(kind)
        for kind, secret in sorted(self.environment_values.items(), key=lambda kv: -len(kv[1])):
            if secret and len(secret) >= 8 and secret in result:
                label = f"{kind.lower()}-env"
                result = result.replace(secret, REDACTION.format(kind=label))
                self.note(label)
        return result

    def scan(self, value: Any) -> Any:
        """Walk a JSON-ish structure, returning a screened copy."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            screened: dict[Any, Any] = {}
            for key, item in value.items():
                if _is_secret_key(str(key)):
                    self.note("secret-field")
                    screened[key] = REDACTION.format(kind="secret-field")
                    continue
                screened[key] = self.scan(item)
            return screened
        if isinstance(value, list):
            return [self.scan(item) for item in value]
        return value

    def summary(self) -> list[dict[str, int]]:
        return [{"kind": kind, "count": count} for kind, count in sorted(self.counts.items())]


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in {name.lower() for name in SECRET_ENVIRONMENT_NAMES} or lowered.endswith(
        ("_api_key", "_secret", "_password", "_token")
    )


def environment_secret_values(names: dict[str, str] | None = None) -> dict[str, str]:
    """The values of the known-secret environment variables that are set.

    Only the value of a variable whose *name* is on the list is collected; no
    other variable is read, so the screen cannot accidentally gather something
    it was never meant to look at.
    """
    import os

    source = os.environ if names is None else names
    return {name: value for name, value in source.items() if name in SECRET_ENVIRONMENT_NAMES}


def redact(
    value: Any, *, environment: dict[str, str] | None = None
) -> tuple[Any, list[dict[str, int]]]:
    """Screen a structure and return it with the summary of what was withheld."""
    redactor = Redactor(environment_values=environment_secret_values(environment))
    return redactor.scan(value), redactor.summary()
