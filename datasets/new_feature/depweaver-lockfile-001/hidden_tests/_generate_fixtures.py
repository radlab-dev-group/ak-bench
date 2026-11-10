"""Regenerate the data fixtures next to this file with the reference solution.

Run from a workspace that has the reference solution copied in:

    PYTHONPATH=<workspace>/src python _generate_fixtures.py

Writes data/<name>/{catalog.json, request.json, lock.json, lock.proof.json}
and data/goldens.json. Deterministic: the large catalog is generated from a
fixed seed and the first seed whose solution is provable is kept.
"""

import json
import random
import sys
from pathlib import Path

from depweaver import Dependency, Policy, Release, Repository, Request, Resolver, Target
from depweaver import codec
from depweaver.canonical import lock_digest
from depweaver.lockfile import Lockfile
from depweaver.proofs import prove, verify_proof
from depweaver.validation import require_valid

DATA = Path(__file__).parent / "data"


def small_catalog() -> Repository:
    """The worked example of the guide plus a yanked, a prerelease and a pinned case."""

    return Repository(
        [
            Release("app", "2.0.0", (Dependency("core", "==2"),)),
            Release(
                "app",
                "1.0.0",
                (
                    Dependency("core", "==1"),
                    Dependency(
                        "Zeta_Lib",
                        ">=1",
                        marker='sys_platform == "linux" and python_version >= "3.8"',
                    ),
                    Dependency("tracing", "*", marker='extra == "trace"'),
                    Dependency("wincolor", "*", marker='sys_platform == "win32"'),
                ),
                extras=frozenset({"trace"}),
            ),
            Release("core", "1.0.0"),
            Release("core", "2.0.0"),
            Release("core", "3.0.0-rc.1"),
            Release("zeta-lib", "1.0.0", (Dependency("core", "<3"),)),
            Release("zeta-lib", "2.0.0", (Dependency("mid", ">=2"),)),
            Release("mid", "1.0.0"),
            Release("mid", "2.0.0", (Dependency("core", "==2"),)),
            Release("tracing", "1.0.0", (Dependency("core", ">=1"),)),
            Release("tracing", "1.1.0", yanked=True),
            Release("tracing", "1.2.0", requires_python=">=3.13"),
            Release("wincolor", "1.0.0"),
            Release("toolbelt", "1.0.0"),
            Release("toolbelt", "1.1.0"),
            Release("toolbelt", "2.0.0"),
        ]
    )


def small_request() -> Request:
    return Request(
        (
            Dependency("app", extras=frozenset({"trace"})),
            Dependency("core", "==1"),
            Dependency("toolbelt", ">=1"),
        ),
        Target(python_version="3.12.0"),
        locked=(("toolbelt", "1.1.0"),),
    )


def cyclic_catalog() -> Repository:
    """A dependency cycle shares one layer; a diamond sits above it."""

    return Repository(
        [
            Release("alpha", "1.0.0", (Dependency("beta", ">=1"),)),
            Release("beta", "1.0.0", (Dependency("gamma", ">=1"),)),
            Release("gamma", "1.0.0", (Dependency("alpha", ">=1"), Dependency("leaf", "*"))),
            Release("leaf", "1.0.0"),
            Release("leaf", "1.1.0", (Dependency("alpha", "<1"),)),
            Release("top", "1.0.0", (Dependency("alpha", "*"), Dependency("leaf", "*"))),
            Release("top", "1.1.0", (Dependency("leaf", ">=1.1"),)),
        ]
    )


def cyclic_request() -> Request:
    return Request((Dependency("top"),))


def generate_large(seed: int) -> tuple[Repository, Request]:
    rng = random.Random(seed)
    levels = [rng.randint(12, 18) for _ in range(8)]
    names = []
    for level, count in enumerate(levels):
        for index in range(count):
            names.append((level, f"pkg-l{level}-{index:02d}"))
    by_level = {}
    for level, name in names:
        by_level.setdefault(level, []).append(name)
    declared = {name: frozenset({"fast"}) if rng.random() < 0.3 else frozenset() for _, name in names}
    releases = []
    for level, name in names:
        count = rng.randint(2, 5)
        deeper = [other for other_level, other in names if other_level > level]
        extras = declared[name]
        for major in range(1, count + 1):
            dependencies = []
            for target in rng.sample(deeper, min(len(deeper), rng.randint(1, 4))):
                pick = rng.random()
                if pick < 0.35:
                    spec = "*"
                elif pick < 0.6:
                    spec = f">={rng.randint(1, 3)}"
                elif pick < 0.8:
                    spec = f"<{rng.randint(2, 5)}"
                else:
                    spec = f"=={rng.randint(1, 3)}"
                marker = ""
                roll = rng.random()
                if roll < 0.1:
                    marker = 'sys_platform == "linux"'
                elif roll < 0.15:
                    marker = 'sys_platform == "win32"'
                elif roll < 0.2 and extras:
                    marker = 'extra == "fast"'
                dependency_extras = frozenset()
                if declared[target] and rng.random() < 0.3:
                    dependency_extras = frozenset({"fast"})
                dependencies.append(Dependency(target, spec, dependency_extras, marker))
            yanked = rng.random() < 0.06
            requires_python = ">=3.13" if rng.random() < 0.05 else "*"
            releases.append(
                Release(
                    name,
                    f"{major}.0.0",
                    tuple(dependencies),
                    extras,
                    requires_python,
                    yanked,
                )
            )
        if rng.random() < 0.2:
            releases.append(Release(name, f"{count + 1}.0.0-rc.1", (), extras))
    roots = tuple(
        Dependency(name, "*", declared[name] if rng.random() < 0.5 else frozenset())
        for name in rng.sample(by_level[0], 8)
    )
    return Repository(releases), Request(roots, Target(), policy=Policy(max_decisions=50_000))


def large_fixture() -> tuple[Repository, Request]:
    for seed in range(1000):
        catalog, request = generate_large(seed)
        try:
            resolution = Resolver(catalog).solve(request)
            require_valid(catalog, request, resolution)
            proof = prove(catalog, request, resolution)
        except Exception:  # noqa: BLE001 - try the next seed
            continue
        if len(resolution.selected) >= 45 and len(proof.exclusions) >= 60:
            print(f"large fixture: seed {seed}, {len(resolution.selected)} packages, "
                  f"{len(proof.exclusions)} exclusions")
            return catalog, request
    raise SystemExit("no provable large catalog found")


def write_fixture(name: str, catalog: Repository, request: Request) -> dict:
    folder = DATA / name
    folder.mkdir(parents=True, exist_ok=True)
    resolution = Resolver(catalog).solve(request)
    require_valid(catalog, request, resolution)
    lockfile = Lockfile(resolution)
    proof = prove(catalog, request, lockfile)
    verify_proof(request, lockfile, proof, catalog)
    codec.write(folder / "catalog.json", catalog.document())
    codec.write(folder / "request.json", request.document())
    lockfile.write(folder / "lock.json")
    codec.write(folder / "lock.proof.json", proof.document())
    assert codec.request(codec.read(folder / "request.json")).fingerprint == request.fingerprint
    return {
        "digest": lock_digest(lockfile),
        "catalog": catalog.fingerprint,
        "manifest": request.fingerprint,
        "proof_sha256": proof.document()["sha256"],
        "packages": len(resolution.selected),
        "exclusions": len(proof.exclusions),
    }


def main() -> int:
    goldens = {
        "small": write_fixture("small", small_catalog(), small_request()),
        "cyclic": write_fixture("cyclic", cyclic_catalog(), cyclic_request()),
        "large": write_fixture("large", *large_fixture()),
    }
    (DATA / "goldens.json").write_text(json.dumps(goldens, indent=2, sort_keys=True) + "\n")
    print(json.dumps(goldens, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
