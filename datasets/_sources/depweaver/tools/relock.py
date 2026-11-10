"""Re-solve a request against a catalog and publish the lockfile, digest and proof.

    python tools/relock.py --catalog catalog.json --request request.json \
        --output lock.json --canonical --prove

Without ``--canonical`` only the lockfile is written. ``--canonical`` also
prints the canonical digest of the lockfile. ``--prove`` requires
``--canonical`` and writes the proof of solution next to the lockfile as
``<stem>.proof.json``. See docs/lockfile-canonical-form.md.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from depweaver import codec  # noqa: E402
from depweaver.canonical import lock_digest  # noqa: E402
from depweaver.errors import SearchLimit, Unsatisfiable  # noqa: E402
from depweaver.lockfile import Lockfile  # noqa: E402
from depweaver.proofs import ProofUnavailable, prove  # noqa: E402
from depweaver.repository import Repository  # noqa: E402
from depweaver.resolver import Resolver  # noqa: E402
from depweaver.validation import require_valid  # noqa: E402


def proof_path(lock: Path) -> Path:
    return lock.with_name(lock.stem + ".proof.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relock", description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--canonical", action="store_true", help="print the canonical digest")
    parser.add_argument("--prove", action="store_true", help="write the proof of solution")
    arguments = parser.parse_args(argv)
    if arguments.prove and not arguments.canonical:
        print("relock: --prove requires --canonical", file=sys.stderr)
        return 2
    catalog = Repository.read(arguments.catalog)
    request = codec.request(codec.read(arguments.request))
    try:
        resolution = Resolver(catalog).solve(request)
    except Unsatisfiable as error:
        print("relock: unsatisfiable: " + str(error), file=sys.stderr)
        return 1
    except SearchLimit as error:
        print("relock: search limit: " + str(error), file=sys.stderr)
        return 1
    require_valid(catalog, request, resolution)
    lockfile = Lockfile(resolution)
    lockfile.write(arguments.output)
    print(f"lock {arguments.output}")
    if not arguments.canonical:
        return 0
    print(f"digest {lock_digest(lockfile)}")
    if arguments.prove:
        try:
            proof = prove(catalog, request, lockfile)
        except ProofUnavailable as error:
            print("relock: no proof: " + str(error), file=sys.stderr)
            return 1
        destination = proof_path(arguments.output)
        codec.write(destination, proof.document())
        print(f"proof {destination}")
        print("proof-sha256 " + json.loads(destination.read_text())["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
