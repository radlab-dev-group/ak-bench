"""Verify a lockfile's proof of solution offline, without running the solver.

    python tools/verify_lock.py --catalog catalog.json --request request.json \
        --lock lock.json [--proof lock.proof.json] [--expect <digest>]

Prints ``ok <digest>`` and exits 0 when the proof verifies under the catalog.
Exits 1 with ``invalid <digest> <reason>`` when it does not, or with
``digest mismatch: expected <a> got <b>`` when ``--expect`` names another
canonical digest. Exits 2 when there is no proof to verify; produce one with
``tools/relock.py --canonical --prove``.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from depweaver import codec  # noqa: E402
from depweaver.canonical import lock_digest  # noqa: E402
from depweaver.lockfile import Lockfile  # noqa: E402
from depweaver.proofs import Proof, ProofInvalid, verify_proof  # noqa: E402
from depweaver.repository import Repository  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_lock", description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--expect", help="canonical digest the lockfile must have")
    arguments = parser.parse_args(argv)
    proof_path = arguments.proof or arguments.lock.with_name(arguments.lock.stem + ".proof.json")
    if not proof_path.exists():
        print(
            f"verify_lock: no proof at {proof_path}; run tools/relock.py --canonical --prove",
            file=sys.stderr,
        )
        return 2
    catalog = Repository.read(arguments.catalog)
    request = codec.request(codec.read(arguments.request))
    lockfile = Lockfile.read(arguments.lock)
    proof = Proof.load(codec.read(proof_path))
    digest = lock_digest(lockfile)
    if arguments.expect is not None and arguments.expect != digest:
        print(f"digest mismatch: expected {arguments.expect} got {digest}")
        return 1
    try:
        verify_proof(request, lockfile, proof, catalog)
    except ProofInvalid as error:
        print(f"invalid {error.hash} {error.reason}")
        return 1
    print(f"ok {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
