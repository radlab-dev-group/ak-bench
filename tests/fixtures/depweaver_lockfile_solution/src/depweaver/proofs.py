"""Proofs of solution: offline certificates that a lockfile satisfies a manifest.

A proof names the catalog snapshot it was produced under, the chosen releases
in canonical order, the canonical digest of the lockfile, and one
justification clause for every catalog version the solver preferred but did
not choose. ``verify_proof`` checks all of that without running the solver.
Every rejection is a ``ProofInvalid`` carrying the canonical digest of the
lockfile as presented and exactly one reason (see ADR-0004).
"""

from dataclasses import dataclass

from .canonical import canonical_order, lock_digest
from .codec import envelope, unwrap
from .lockfile import Lockfile
from .model import Dependency, Release, Request, Resolution, normalize
from .repository import Repository
from .validation import validate
from .versions import Version

PROOF_KIND = "proof"
MAX_DEPTH = 4


class ProofInvalid(ValueError):
    def __init__(self, *, hash: str, reason: str) -> None:
        self.hash = hash
        self.reason = reason
        super().__init__(f"proof rejected for {hash}: {reason}")


class ProofUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class Exclusion:
    name: str
    version: str
    justification: dict

    def document(self) -> dict:
        return {"name": self.name, "version": self.version, "justification": self.justification}


@dataclass(frozen=True)
class Proof:
    digest: str
    catalog: str
    manifest: str
    chosen: tuple[tuple[str, str], ...]
    exclusions: tuple[Exclusion, ...]

    def payload(self) -> dict:
        return {
            "digest": self.digest,
            "catalog": self.catalog,
            "manifest": self.manifest,
            "chosen": [list(pair) for pair in self.chosen],
            "exclusions": [exclusion.document() for exclusion in self.exclusions],
        }

    def document(self) -> dict:
        return envelope(PROOF_KIND, self.payload())

    @classmethod
    def load(cls, document: dict) -> "Proof":
        payload = unwrap(document, PROOF_KIND)
        if not isinstance(payload, dict) or set(payload) != {
            "digest",
            "catalog",
            "manifest",
            "chosen",
            "exclusions",
        }:
            raise ValueError("invalid proof payload")
        for key in ("digest", "catalog", "manifest"):
            value = payload[key]
            if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
                raise ValueError("invalid proof fingerprint")
        chosen = []
        for pair in payload["chosen"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("invalid chosen release")
            chosen.append((normalize(pair[0]), str(Version.parse(pair[1]))))
        exclusions = []
        for row in payload["exclusions"]:
            if not isinstance(row, dict) or set(row) != {"name", "version", "justification"}:
                raise ValueError("invalid proof exclusion")
            if not isinstance(row["justification"], dict) or "kind" not in row["justification"]:
                raise ValueError("invalid proof justification")
            exclusions.append(
                Exclusion(
                    normalize(row["name"]), str(Version.parse(row["version"])), row["justification"]
                )
            )
        return cls(
            payload["digest"],
            payload["catalog"],
            payload["manifest"],
            tuple(chosen),
            tuple(exclusions),
        )


@dataclass(frozen=True)
class Context:
    """Everything a justification is checked against; derived, never trusted."""

    catalog: Repository
    manifest: Request
    resolution: Resolution
    selected: dict[str, Release]
    features: dict[str, frozenset[str]]
    clauses: dict[str, tuple[tuple[tuple[str, str] | None, Dependency], ...]]

    @classmethod
    def build(cls, catalog: Repository, manifest: Request, resolution: Resolution) -> "Context":
        selected = {release.name: release for release in resolution.selected}
        features = {name: frozenset(extras) for name, extras in resolution.extras}
        clauses: dict[str, list] = {}
        for root in manifest.roots:
            if root.marker.matches(manifest.target):
                clauses.setdefault(root.name, []).append((None, root))
        for name in sorted(selected):
            release = selected[name]
            for dependency in release.dependencies:
                if dependency.marker.matches(manifest.target, features.get(name, frozenset())):
                    clauses.setdefault(dependency.name, []).append((release.identity, dependency))
        return cls(
            catalog,
            manifest,
            resolution,
            selected,
            features,
            {name: tuple(rows) for name, rows in clauses.items()},
        )

    def pinned(self, name: str) -> str | None:
        locked = dict(self.manifest.locked).get(name)
        if locked is None or name in self.manifest.update:
            return None
        return locked

    def same_lock(self, release: Release) -> bool:
        locked = dict(self.manifest.locked).get(release.name)
        return locked is not None and Version.parse(locked) == release.version

    def preferred(self, release: Release) -> tuple[Release, ...]:
        """Catalog versions the policy would have chosen before ``release``, ascending."""

        lowest = self.manifest.policy.prefer_lowest
        candidates = [
            candidate
            for candidate in self.catalog.versions(release.name)
            if candidate.version != release.version
            and (
                self.pinned(release.name) is not None
                or (candidate.version < release.version) == lowest
            )
        ]
        return tuple(sorted(candidates, key=lambda candidate: candidate.version))


def _clause_document(parent: tuple[str, str] | None, dependency: Dependency) -> dict:
    return {"parent": list(parent) if parent else None, "dependency": dependency.document()}


def _clause_matches(context: Context, package: str, row: dict, enclosing) -> Dependency | None:
    """Return the dependency of an active clause ``row`` for ``package`` or None."""

    try:
        dependency = Dependency.load(row["dependency"])
    except (KeyError, TypeError, ValueError):
        return None
    if dependency.name != package:
        return None
    parent = tuple(row["parent"]) if row.get("parent") is not None else None
    if enclosing is not None and parent == enclosing[0] and dependency == enclosing[1]:
        return dependency
    for candidate_parent, candidate in context.clauses.get(package, ()):
        if candidate_parent == parent and candidate == dependency:
            return dependency
    return None


def _holds(context: Context, release: Release, justification: dict, enclosing, depth: int) -> bool:
    """Decide whether ``justification`` really excludes ``release``."""

    if depth < 0 or not isinstance(justification, dict):
        return False
    kind = justification.get("kind")
    name = release.name
    if kind == "pin":
        pinned = context.pinned(name)
        return pinned is not None and Version.parse(pinned) != release.version
    if kind == "python":
        python = Version.coerce(context.manifest.target.python_version)
        return not release.requires_python.matches(python)
    if kind == "yanked":
        return (
            release.yanked
            and not context.manifest.policy.allow_yanked
            and not context.same_lock(release)
        )
    if kind == "prerelease":
        clauses = [dependency for _parent, dependency in context.clauses.get(name, ())]
        if enclosing is not None and enclosing[1].name == name:
            clauses.append(enclosing[1])
        return (
            bool(release.version.prerelease)
            and not context.manifest.policy.allow_prerelease
            and not context.same_lock(release)
            and not any(dependency.spec.allows_prerelease for dependency in clauses)
        )
    if kind in {"range", "extras"}:
        dependency = _clause_matches(context, name, justification, enclosing)
        if dependency is None:
            return False
        if kind == "range":
            return not dependency.spec.matches(release.version)
        return not dependency.extras <= release.extras
    if kind == "conflict":
        try:
            dependency = Dependency.load(justification["dependency"])
        except (KeyError, TypeError, ValueError):
            return False
        if dependency not in release.dependencies:
            return False
        features = context.features.get(name, frozenset())
        if enclosing is not None and enclosing[1].name == name:
            features = features | enclosing[1].extras
        if not dependency.marker.matches(context.manifest.target, features):
            return False
        if "chosen" in justification:
            chosen = context.selected.get(dependency.name)
            if chosen is None or list(chosen.identity) != list(justification["chosen"]):
                return False
            return not dependency.spec.matches(chosen.version) or not (
                dependency.extras <= chosen.extras
            )
        if "candidates" in justification:
            if dependency.name in context.selected:
                return False
            candidates = justification["candidates"]
            if not isinstance(candidates, dict):
                return False
            inner = (release.identity, dependency)
            for candidate in context.catalog.versions(dependency.name):
                if not dependency.spec.matches(candidate.version):
                    continue
                nested = candidates.get(str(candidate.version))
                if nested is None or not _holds(context, candidate, nested, inner, depth - 1):
                    return False
            return True
    return False


def _justify(context: Context, release: Release, enclosing, depth: int) -> dict | None:
    """Find a justification for excluding ``release``; the shape mirrors ``_holds``."""

    if depth < 0:
        return None
    for kind in ("pin", "python", "yanked", "prerelease"):
        candidate = {"kind": kind}
        if _holds(context, release, candidate, enclosing, depth):
            return candidate
    clauses = list(context.clauses.get(release.name, ()))
    if enclosing is not None and enclosing[1].name == release.name:
        clauses.append(enclosing)
    for parent, dependency in clauses:
        for kind in ("range", "extras"):
            candidate = {"kind": kind, **_clause_document(parent, dependency)}
            if _holds(context, release, candidate, enclosing, depth):
                return candidate
    features = context.features.get(release.name, frozenset())
    if enclosing is not None and enclosing[1].name == release.name:
        features = features | enclosing[1].extras
    for dependency in release.dependencies:
        if not dependency.marker.matches(context.manifest.target, features):
            continue
        chosen = context.selected.get(dependency.name)
        if chosen is not None:
            candidate = {
                "kind": "conflict",
                "dependency": dependency.document(),
                "chosen": list(chosen.identity),
            }
            if _holds(context, release, candidate, enclosing, depth):
                return candidate
            continue
        inner = (release.identity, dependency)
        nested = {}
        complete = True
        for option in context.catalog.versions(dependency.name):
            if not dependency.spec.matches(option.version):
                continue
            justification = _justify(context, option, inner, depth - 1)
            if justification is None:
                complete = False
                break
            nested[str(option.version)] = justification
        if complete:
            candidate = {
                "kind": "conflict",
                "dependency": dependency.document(),
                "candidates": nested,
            }
            if _holds(context, release, candidate, enclosing, depth):
                return candidate
    return None


def prove(catalog: Repository, manifest: Request, value: Lockfile | Resolution) -> Proof:
    resolution = value.resolution if isinstance(value, Lockfile) else value
    violations = validate(catalog, manifest, resolution)
    if violations:
        raise ProofUnavailable(
            "; ".join(f"{item.code}:{item.package}: {item.message}" for item in violations)
        )
    context = Context.build(catalog, manifest, resolution)
    exclusions = []
    for name in sorted(context.selected):
        release = context.selected[name]
        for candidate in context.preferred(release):
            justification = _justify(context, candidate, None, MAX_DEPTH)
            if justification is None:
                raise ProofUnavailable(f"no justification for excluding {name} {candidate.version}")
            exclusions.append(Exclusion(name, str(candidate.version), justification))
    exclusions.sort(key=lambda item: (item.name, Version.parse(item.version)))
    return Proof(
        lock_digest(resolution),
        catalog.fingerprint,
        manifest.fingerprint,
        canonical_order(resolution),
        tuple(exclusions),
    )


def verify_proof(manifest: Request, lockfile: Lockfile, proof: Proof, catalog: Repository) -> None:
    resolution = lockfile.resolution
    digest = lock_digest(resolution)

    def reject(reason: str) -> None:
        raise ProofInvalid(hash=digest, reason=reason)

    if proof.digest != digest:
        reject("canonical digest mismatch")
    if proof.chosen != canonical_order(resolution):
        reject("chosen releases are not in canonical order")
    if proof.catalog != catalog.fingerprint:
        reject("catalog digest is stale")
    if proof.manifest != manifest.fingerprint:
        reject("manifest fingerprint mismatch")
    violations = validate(catalog, manifest, resolution)
    if violations:
        reject("lockfile does not satisfy manifest: " + violations[0].code)
    context = Context.build(catalog, manifest, resolution)
    presented = {}
    for exclusion in proof.exclusions:
        key = (exclusion.name, Version.parse(exclusion.version))
        if key in presented:
            reject(f"duplicate justification for {exclusion.name} {exclusion.version}")
        presented[key] = exclusion.justification
    for name in sorted(context.selected):
        for candidate in context.preferred(context.selected[name]):
            justification = presented.pop((name, candidate.version), None)
            if justification is None:
                reject(f"missing justification for {name} {candidate.version}")
            if not _holds(context, candidate, justification, None, MAX_DEPTH):
                reject(f"justification does not hold for {name} {candidate.version}")
    if presented:
        name, version = sorted(presented)[0]
        reject(f"justification for an unselected exclusion {name} {version}")
