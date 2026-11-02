"""Strict request/report transport and atomic canonical JSON publication."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .markers import Target
from .model import Dependency, Policy, Request, canonical


def object_fields(value: object, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or not required <= value.keys():
        raise ValueError("missing object fields: " + ", ".join(sorted(required)))
    if value.keys() - required - optional:
        raise ValueError("unknown object fields")
    return value


def strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(label + " must be a string array")
    return tuple(value)


def policy(value: object) -> Policy:
    fields = {"allow_prerelease", "allow_yanked", "prefer_lowest", "max_decisions"}
    row = object_fields(value, set(), fields)
    for name in fields - {"max_decisions"}:
        if name in row and type(row[name]) is not bool:
            raise ValueError("policy flags must be booleans")
    budget = row.get("max_decisions", 100_000)
    if type(budget) is not int or budget < 1:
        raise ValueError("max_decisions must be a positive integer")
    return Policy(**row)


def target(value: object) -> Target:
    row = object_fields(
        value, set(), {"python_version", "sys_platform", "platform_machine", "implementation_name"}
    )
    if any(not isinstance(item, str) for item in row.values()):
        raise ValueError("target fields must be strings")
    return Target(**row)


def request(value: object) -> Request:
    row = object_fields(value, {"roots"}, {"target", "policy", "locked", "update"})
    if not isinstance(row["roots"], list):
        raise ValueError("roots must be an array")
    roots = []
    for item in row["roots"]:
        object_fields(item, {"name"}, {"spec", "extras", "marker"})
        if "extras" in item:
            strings(item["extras"], "extras")
        roots.append(Dependency.load(item))
    locked = row.get("locked", {})
    if not isinstance(locked, dict) or any(
        not isinstance(version, str) for version in locked.values()
    ):
        raise ValueError("locked must map names to version strings")
    return Request(
        tuple(roots),
        target(row.get("target", {})),
        tuple(locked.items()),
        frozenset(strings(row.get("update", []), "update")),
        policy(row.get("policy", {})),
    )


def envelope(kind: str, payload: object) -> dict:
    if not kind:
        raise ValueError("empty document kind")
    body = {"version": 1, "kind": kind, "payload": payload}
    return {"body": body, "sha256": hashlib.sha256(canonical(body).encode()).hexdigest()}


def unwrap(value: object, kind: str) -> object:
    row = object_fields(value, {"body", "sha256"})
    body = object_fields(row["body"], {"version", "kind", "payload"})
    if body["version"] != 1 or body["kind"] != kind:
        raise ValueError("unsupported document version or kind")
    if hashlib.sha256(canonical(body).encode()).hexdigest() != row["sha256"]:
        raise ValueError("document checksum mismatch")
    return body["payload"]


def read(path: Path) -> object:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(
        Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=invalid
    )


def write(path: Path, document: object) -> None:
    data = canonical(document) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".depweaver-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
