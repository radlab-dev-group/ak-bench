"""Proofs of solution — declared, not implemented.

A proof is a compact certificate that a lockfile satisfies a manifest under a
given catalog snapshot: the chosen releases in canonical order, the canonical
digest of the lockfile, the catalog digest, and one justification clause for
every catalog version the policy preferred but the solution does not contain.
It is verified offline, without running the solver. The contract is SPEC.md,
section "Lockfile canonical form and proofs"; the reasons are in docs/adr/.

The transport (``Proof.document`` / ``Proof.load``) and the error type are
complete. ``prove`` and ``verify_proof`` raise NotImplementedError.
"""

from dataclasses import dataclass

from .codec import envelope, unwrap
from .lockfile import Lockfile
from .model import Request, Resolution, normalize
from .repository import Repository
from .versions import Version

PROOF_KIND = "proof"


class ProofInvalid(ValueError):
    """One hash, one reason: the canonical digest of the lockfile as presented."""

    def __init__(self, *, hash: str, reason: str) -> None:
        self.hash = hash
        self.reason = reason
        super().__init__(f"proof rejected for {hash}: {reason}")


class ProofUnavailable(ValueError):
    """The prover found no justification; this is not a verification failure."""


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


def prove(catalog: Repository, manifest: Request, value: Lockfile | Resolution) -> Proof:
    """Build the proof of solution for a valid resolution under ``catalog``."""
    raise NotImplementedError("proofs are declared in SPEC.md but not implemented")


def verify_proof(manifest: Request, lockfile: Lockfile, proof: Proof, catalog: Repository) -> None:
    """Return None when the proof verifies; raise ProofInvalid(hash=..., reason=...) otherwise."""
    raise NotImplementedError("proofs are declared in SPEC.md but not implemented")
