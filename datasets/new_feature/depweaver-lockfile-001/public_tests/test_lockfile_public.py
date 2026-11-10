"""Public acceptance tests for the canonical lockfile form and proofs of solution."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from depweaver import Dependency, Release, Repository, Request, Resolver
from depweaver import codec
from depweaver.canonical import canonical_marker, canonical_order, lock_digest
from depweaver.lockfile import Lockfile
from depweaver.proofs import ProofInvalid, prove, verify_proof
from depweaver.store import Store

TOOLS = Path.cwd() / "tools"


def catalog():
    return Repository(
        [
            Release("app", "2.0.0", (Dependency("core", "==2"),)),
            Release(
                "app",
                "1.0.0",
                (Dependency("core", "==1"), Dependency("Zeta_Lib", ">=1", marker="sys_platform == 'linux'")),
            ),
            Release("core", "1.0.0"),
            Release("core", "2.0.0"),
            Release("zeta-lib", "1.0.0", (Dependency("core", "<3"),)),
        ]
    )


def request():
    return Request((Dependency("app"), Dependency("core", "==1")))


def test_canonical_order_puts_dependencies_before_dependents():
    resolution = Resolver(catalog()).solve(request())
    assert sorted(resolution.versions()) == ["app", "core", "zeta-lib"]
    assert canonical_order(resolution) == (("core", "1.0.0"), ("zeta-lib", "1.0.0"), ("app", "1.0.0"))


def test_marker_spelling_does_not_change_the_canonical_text():
    assert canonical_marker("sys_platform == 'linux'") == 'sys_platform == "linux"'
    assert canonical_marker('extra == "fast" and python_version >= "3.8"') == canonical_marker(
        "python_version >= '3.8.0' and extra == 'fast'"
    )


def test_lock_digest_is_stable_across_catalog_spellings():
    first = Resolver(catalog()).solve(request())
    document = catalog().document()
    document["releases"].reverse()
    for release in document["releases"]:
        release["dependencies"].reverse()
        for dependency in release["dependencies"]:
            dependency["marker"] = dependency["marker"].replace("'", '"')
    second = Resolver(Repository.load(document)).solve(request())
    assert first.repository_fingerprint != second.repository_fingerprint
    assert lock_digest(first) == lock_digest(second) == lock_digest(Lockfile(first))
    assert len(lock_digest(first)) == 64


def test_proof_is_generated_once_and_verified_offline():
    repository = catalog()
    manifest = request()
    lockfile = Lockfile(Resolver(repository).solve(manifest))
    proof = prove(repository, manifest, lockfile)
    assert proof.digest == lock_digest(lockfile)
    assert proof.catalog == repository.fingerprint
    assert proof.chosen == canonical_order(lockfile)
    assert {(item.name, item.version) for item in proof.exclusions} == {("app", "2.0.0"), ("core", "2.0.0")}
    assert verify_proof(manifest, lockfile, proof, repository) is None
    moved = Repository(repository.all() + (Release("core", "1.5.0"),))
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(manifest, lockfile, proof, moved)
    assert caught.value.hash == lock_digest(lockfile)
    assert caught.value.reason
    assert str(caught.value) == f"proof rejected for {caught.value.hash}: {caught.value.reason}"


def test_store_forgets_a_cached_resolution_when_its_proof_stops_verifying(tmp_path):
    repository = catalog()
    manifest = request()
    lockfile = Lockfile(Resolver(repository).solve(manifest))
    proof = prove(repository, manifest, lockfile)
    store = Store(tmp_path)
    store.remember(manifest, lockfile, proof)
    assert store.recall(manifest, repository) == lockfile
    moved = Repository(repository.all() + (Release("core", "1.5.0"),))
    assert store.recall(manifest, moved) is None
    assert store.recall(manifest, repository) is None


def test_relock_then_verify_lock(tmp_path):
    codec.write(tmp_path / "catalog.json", catalog().document())
    codec.write(tmp_path / "request.json", request().document())
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    common = ["--catalog", str(tmp_path / "catalog.json"), "--request", str(tmp_path / "request.json")]
    relock = subprocess.run(
        [sys.executable, str(TOOLS / "relock.py"), *common, "--output", str(tmp_path / "lock.json"), "--canonical", "--prove"],
        cwd=str(tmp_path),
        env=environment,
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert relock.returncode == 0, relock.stdout + relock.stderr
    digest = next(line.split()[1] for line in relock.stdout.splitlines() if line.startswith("digest "))
    assert digest == lock_digest(Lockfile.read(tmp_path / "lock.json"))
    assert json.loads((tmp_path / "lock.proof.json").read_text())["body"]["kind"] == "proof"
    verify = subprocess.run(
        [sys.executable, str(TOOLS / "verify_lock.py"), *common, "--lock", str(tmp_path / "lock.json"), "--expect", digest],
        cwd=str(tmp_path),
        env=environment,
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert verify.stdout.strip() == f"ok {digest}"
