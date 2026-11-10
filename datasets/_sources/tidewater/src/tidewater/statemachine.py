"""The applied state: a small key-value map.

The state machine is deliberately dull. Its job is to make *state machine
safety* observable: two nodes that applied the same prefix of the log must
hold byte-identical state, and :meth:`KVStateMachine.digest` is how the
invariant checker and the trace digest tell. Commands are deterministic
functions of the current state; nothing in here looks at time, node
identity or the term of the entry being applied.

Supported operations::

    set  key value       store a string
    del  key             remove a key (a no-op if absent)
    incr key [amount]    integer add; a missing key counts as 0
    cas  key expect new  compare-and-set; applies only if the current value
                         equals ``expect`` (an absent key equals "")

``cas`` exists so that an applied command can *fail* deterministically and
the result still be part of the state (``last_result``), which makes
"applied in a different order" visible even when the final map happens to
coincide.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

OP_SET = "set"
OP_DEL = "del"
OP_INCR = "incr"
OP_CAS = "cas"

OPERATIONS = (OP_SET, OP_DEL, OP_INCR, OP_CAS)


@dataclass(frozen=True)
class Command:
    """A client command. ``client`` and ``seq`` identify it for the trace and
    for a future deduplication layer; the state machine ignores them."""

    op: str
    key: str
    value: str = ""
    expect: str = ""
    client: str = ""
    seq: int = 0

    def __post_init__(self) -> None:
        if self.op not in OPERATIONS:
            raise ValueError(f"unknown operation {self.op!r}; the state machine knows {OPERATIONS}")
        if not self.key:
            raise ValueError("a command needs a key")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"op": self.op, "key": self.key}
        if self.value:
            out["value"] = self.value
        if self.expect:
            out["expect"] = self.expect
        if self.client:
            out["client"] = self.client
        if self.seq:
            out["seq"] = self.seq
        return out

    def summary(self) -> str:
        if self.op == OP_SET:
            return f"set {self.key}={self.value}"
        if self.op == OP_DEL:
            return f"del {self.key}"
        if self.op == OP_INCR:
            return f"incr {self.key} {self.value or 1}"
        return f"cas {self.key} {self.expect!r}->{self.value!r}"


def command_from_dict(data: dict[str, Any]) -> Command:
    return Command(
        op=data["op"],
        key=data["key"],
        value=str(data.get("value", "")),
        expect=str(data.get("expect", "")),
        client=str(data.get("client", "")),
        seq=int(data.get("seq", 0)),
    )


@dataclass
class ApplyResult:
    index: int
    ok: bool
    value: str

    def summary(self) -> str:
        return f"{'ok' if self.ok else 'fail'} {self.value!r}"


@dataclass
class KVStateMachine:
    """The map plus the index of the last applied entry."""

    data: dict[str, str] = field(default_factory=dict)
    last_applied: int = 0
    last_result: ApplyResult | None = None
    applied_count: int = 0

    def apply(self, index: int, command: Command | None) -> ApplyResult:
        """Apply the command for log index ``index``. Indexes must be applied
        in order with no gaps; a ``None`` command (a no-op or a configuration
        entry) advances ``last_applied`` without touching the map."""

        if index != self.last_applied + 1:
            raise ValueError(f"apply out of order: expected {self.last_applied + 1}, got {index}")
        self.last_applied = index
        self.applied_count += 1
        if command is None:
            result = ApplyResult(index, True, "")
        elif command.op == OP_SET:
            self.data[command.key] = command.value
            result = ApplyResult(index, True, command.value)
        elif command.op == OP_DEL:
            previous = self.data.pop(command.key, "")
            result = ApplyResult(index, True, previous)
        elif command.op == OP_INCR:
            amount = int(command.value or 1)
            current = int(self.data.get(command.key, "0") or 0)
            self.data[command.key] = str(current + amount)
            result = ApplyResult(index, True, self.data[command.key])
        else:  # OP_CAS
            current = self.data.get(command.key, "")
            if current == command.expect:
                self.data[command.key] = command.value
                result = ApplyResult(index, True, command.value)
            else:
                result = ApplyResult(index, False, current)
        self.last_result = result
        return result

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def snapshot_bytes(self) -> bytes:
        """Canonical encoding of the state, used by the digest and — once
        implemented — by snapshot transfer."""

        body = {
            "last_applied": self.last_applied,
            "data": {k: self.data[k] for k in sorted(self.data)},
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.snapshot_bytes()).hexdigest()

    @classmethod
    def from_snapshot_bytes(cls, raw: bytes) -> "KVStateMachine":
        body = json.loads(raw.decode("utf-8"))
        return cls(data=dict(body["data"]), last_applied=int(body["last_applied"]))

    def reset(self) -> None:
        self.data.clear()
        self.last_applied = 0
        self.last_result = None
        self.applied_count = 0

    def summary(self) -> str:
        items = ", ".join(f"{k}={v}" for k, v in sorted(self.data.items())[:6])
        more = f" (+{len(self.data) - 6})" if len(self.data) > 6 else ""
        return f"applied={self.last_applied} {{{items}}}{more}"
