"""Canonical form, lock digest, proofs of solution, cache invalidation and the procedure.

The data fixtures next to this file were produced by the reference solution
with `_generate_fixtures.py`: three catalogs (the guide's worked example, a
cycle, and a generated one with 61 selected packages), their requests, the
lockfiles and the proofs, plus `goldens.json` with the digests the procedure
must reproduce.
"""

import copy
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest
from depweaver import Dependency, Marker, Release, Repository, Request, Resolver, Target, Version
from depweaver import codec
from depweaver.canonical import (
    canonical_document,
    canonical_marker,
    canonical_order,
    canonical_version,
    layers,
    lock_digest,
)
from depweaver.lockfile import Lockfile
from depweaver.proofs import Proof, ProofInvalid, prove, verify_proof
from depweaver.session import Session
from depweaver.store import Store

DATA = Path(__file__).parent / "data"
GOLDENS = json.loads((DATA / "goldens.json").read_text())
TOOLS = Path.cwd() / "tools"
HEX = set("0123456789abcdef")


def fixture(name):
    folder = DATA / name
    catalog = Repository.read(folder / "catalog.json")
    request = codec.request(codec.read(folder / "request.json"))
    lockfile = Lockfile.read(folder / "lock.json")
    proof = Proof.load(codec.read(folder / "lock.proof.json"))
    return catalog, request, lockfile, proof


def reproof(proof, **changes):
    """Rebuild a Proof from a tampered payload through the codec, as a tool would."""

    payload = copy.deepcopy(proof.payload())
    for key, value in changes.items():
        payload[key] = value
    return Proof.load(codec.envelope("proof", payload))


def permuted(document, rng, *, quotes=False, build=False):
    """A catalog document with the same meaning and a different spelling."""

    document = copy.deepcopy(document)
    rng.shuffle(document["releases"])
    for release in document["releases"]:
        rng.shuffle(release["dependencies"])
        release["extras"] = list(reversed(release["extras"]))
        for dependency in release["dependencies"]:
            dependency["extras"] = list(reversed(dependency["extras"]))
            if quotes:
                dependency["marker"] = dependency["marker"].replace('"', "'")
                dependency["name"] = dependency["name"].upper().replace("-", "_")
        if build and rng.random() < 0.5 and "-" not in release["version"]:
            release["version"] += f"+build.{rng.randint(1, 99)}"
    return document


def run_tool(name, *arguments, cwd):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, str(TOOLS / name), *map(str, arguments)],
        cwd=str(cwd),
        env=environment,
        text=True,
        capture_output=True,
        timeout=600,
    )


# --- canonical form -------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("", ""),
        ("sys_platform == 'linux'", 'sys_platform == "linux"'),
        ('python_version >= "3.8"', 'python_version >= "3.8.0"'),
        ('python_version in "3.11,3.10"', 'python_version in "3.10,3.11"'),
        ('python_version in "3.11,3.10,3.11"', 'python_version in "3.10,3.11"'),
        (
            'sys_platform == "linux" and extra == "fast"',
            'extra == "fast" and sys_platform == "linux"',
        ),
        (
            'extra == "fast" and sys_platform == "linux"',
            'extra == "fast" and sys_platform == "linux"',
        ),
        (
            'sys_platform == "linux" and (extra == "fast" or extra == "safe")',
            '(extra == "fast" or extra == "safe") and sys_platform == "linux"',
        ),
        (
            '(sys_platform == "linux" and extra == "fast") and platform_machine == "x86_64"',
            'extra == "fast" and platform_machine == "x86_64" and sys_platform == "linux"',
        ),
        ('extra == "fast" or extra == "fast"', 'extra == "fast"'),
        (
            'extra == "fast" or sys_platform == "linux" and extra == "safe"',
            'extra == "fast" or extra == "safe" and sys_platform == "linux"',
        ),
        ('python_version not in "3.9, 3.8"', 'python_version not in " 3.8,3.9"'),
    ],
)
def test_marker_rule_m(written, expected):
    assert canonical_marker(Marker(written)) == expected
    assert canonical_marker(written) == expected
    assert canonical_marker(expected) == expected


def test_canonical_order_is_layered_install_order_not_alphabetical():
    catalog, request, lockfile, _proof = fixture("small")
    assert sorted(lockfile.resolution.versions()) == ["app", "core", "toolbelt", "tracing", "zeta-lib"]
    assert layers(lockfile.resolution) == {
        "core": 0,
        "toolbelt": 0,
        "tracing": 1,
        "zeta-lib": 1,
        "app": 2,
    }
    assert canonical_order(lockfile) == (
        ("core", "1.0.0"),
        ("toolbelt", "1.1.0"),
        ("tracing", "1.0.0"),
        ("zeta-lib", "1.0.0"),
        ("app", "1.0.0"),
    )
    rows = canonical_document(lockfile)["packages"]
    assert [row["name"] for row in rows] != sorted(row["name"] for row in rows)
    assert [(row["layer"], row["name"]) for row in rows] == sorted(
        (row["layer"], row["name"]) for row in rows
    )
    app = next(row for row in rows if row["name"] == "app")
    assert app["extras"] == ["trace"] and app["provides"] == ["trace"]
    assert [item["name"] for item in app["requires"]] == ["core", "tracing", "wincolor", "zeta-lib"]
    assert next(item for item in app["requires"] if item["name"] == "zeta-lib")["marker"] == (
        'python_version >= "3.8.0" and sys_platform == "linux"'
    )


def test_inactive_edges_do_not_build_layers():
    catalog, request, lockfile, _proof = fixture("small")
    # `wincolor` is a dependency of app under sys_platform == "win32": not selected, not an edge.
    assert "wincolor" not in lockfile.resolution.versions()
    # An edge to a selected package under a false marker must not raise the layer.
    release = Release(
        "shadow", "1.0.0", (Dependency("app", "*", marker='sys_platform == "win32"'),)
    )
    resolution = lockfile.resolution
    patched = type(resolution)(
        resolution.selected + (release,),
        resolution.extras + (("shadow", ()),),
        resolution.target,
        resolution.request_fingerprint,
        resolution.repository_fingerprint,
    )
    assert layers(patched)["shadow"] == 0
    assert canonical_order(patched)[0] == ("core", "1.0.0")
    assert ("shadow", "1.0.0") in canonical_order(patched)[:3]


def test_cycle_members_share_a_layer():
    catalog, request, lockfile, proof = fixture("cyclic")
    assert layers(lockfile.resolution) == {"leaf": 0, "alpha": 1, "beta": 1, "gamma": 1, "top": 2}
    assert canonical_order(lockfile) == (
        ("leaf", "1.0.0"),
        ("alpha", "1.0.0"),
        ("beta", "1.0.0"),
        ("gamma", "1.0.0"),
        ("top", "1.0.0"),
    )
    assert lock_digest(lockfile) == GOLDENS["cyclic"]["digest"]
    verify_proof(request, lockfile, proof, catalog)


def test_versions_render_without_build_metadata_and_names_normalise():
    assert canonical_version("1.10.0+build.3") == "1.10.0"
    assert canonical_version(Version.parse("2.0.0-rc.1+exp")) == "2.0.0-rc.1"
    request = Request((Dependency("Pkg_A"), Dependency("pkg.b")))
    plain = Resolver(
        Repository([Release("pkg-a", "1.10.0"), Release("pkg-b", "1.9.0")])
    ).solve(request)
    built = Resolver(
        Repository([Release("PKG_A", "1.10.0+build.3"), Release("pkg.B", "1.9.0+7")])
    ).solve(request)
    assert plain.repository_fingerprint != built.repository_fingerprint
    rows = canonical_document(built)["packages"]
    assert [(row["name"], row["version"]) for row in rows] == [("pkg-a", "1.10.0"), ("pkg-b", "1.9.0")]
    assert lock_digest(plain) == lock_digest(built)


@pytest.mark.parametrize("name", ["small", "cyclic", "large"])
def test_lock_digest_matches_golden_and_is_stable(name):
    catalog, request, lockfile, proof = fixture(name)
    golden = GOLDENS[name]
    assert lock_digest(lockfile) == golden["digest"] == proof.digest
    assert lock_digest(lockfile.resolution) == golden["digest"]
    assert canonical_order(lockfile) == proof.chosen
    assert len(lockfile.resolution.selected) == golden["packages"]
    assert catalog.fingerprint == golden["catalog"] and request.fingerprint == golden["manifest"]


@pytest.mark.parametrize("name", ["small", "large"])
def test_canonical_form_is_invariant_under_permuted_catalogs(name):
    catalog, request, lockfile, _proof = fixture(name)
    rng = random.Random(7)
    seen = set()
    rounds = 4 if name == "small" else 2
    for round_number in range(rounds):
        document = permuted(
            catalog.document(),
            rng,
            quotes=round_number % 2 == 1,
            build=round_number >= rounds // 2,
        )
        other = Repository.load(document)
        seen.add(other.fingerprint)
        resolution = Resolver(other).solve(request)
        assert {
            package: canonical_version(version) for package, version in resolution.versions().items()
        } == lockfile.resolution.versions()
        assert canonical_document(resolution) == canonical_document(lockfile)
        assert lock_digest(resolution) == GOLDENS[name]["digest"]
        assert lock_digest(Lockfile.load(json.loads(json.dumps(Lockfile(resolution).document())))) == (
            GOLDENS[name]["digest"]
        )
    assert len(seen) == rounds, "permutations must produce distinct catalog fingerprints"


def test_digest_changes_when_the_solution_changes():
    catalog, request, lockfile, _proof = fixture("small")
    without_pin = Request(request.roots, request.target, (), request.update, request.policy)
    moved = Resolver(catalog).solve(without_pin)
    assert moved.versions()["toolbelt"] == "2.0.0"
    assert lock_digest(moved) != lock_digest(lockfile)
    other_target = Request(
        request.roots, Target(sys_platform="darwin"), request.locked, request.update, request.policy
    )
    retargeted = Resolver(catalog).solve(other_target)
    assert retargeted.versions() != lockfile.resolution.versions()
    assert lock_digest(retargeted) != lock_digest(lockfile)


# --- proofs ----------------------------------------------------------------


def test_prove_reproduces_the_fixture_proof_and_verifies_offline(monkeypatch):
    for name in ("small", "cyclic", "large"):
        catalog, request, lockfile, proof = fixture(name)
        fresh = prove(catalog, request, lockfile)
        assert fresh == proof
        assert fresh.document()["sha256"] == GOLDENS[name]["proof_sha256"]
        verify_proof(request, lockfile, proof, catalog)
    import depweaver.resolver as resolver_module

    def no_solver(*_arguments, **_options):
        raise AssertionError("verification must not run the solver")

    monkeypatch.setattr(resolver_module.Resolver, "solve", no_solver)
    monkeypatch.setattr(resolver_module.Resolver, "__init__", no_solver)
    for name in ("small", "cyclic", "large"):
        catalog, request, lockfile, proof = fixture(name)
        assert verify_proof(request, lockfile, proof, catalog) is None


def test_small_proof_uses_every_justification_kind():
    catalog, request, lockfile, proof = fixture("small")
    kinds = {(item.name, item.version): item.justification for item in proof.exclusions}
    assert kinds[("app", "2.0.0")]["kind"] == "extras"
    assert kinds[("app", "2.0.0")]["parent"] is None
    assert kinds[("core", "2.0.0")] == {
        "kind": "range",
        "parent": None,
        "dependency": {"name": "core", "spec": "==1.0.0", "extras": [], "marker": ""},
    }
    assert kinds[("core", "3.0.0-rc.1")] == {"kind": "prerelease"}
    assert kinds[("toolbelt", "1.0.0")] == {"kind": "pin"}
    assert kinds[("toolbelt", "2.0.0")] == {"kind": "pin"}
    assert kinds[("tracing", "1.1.0")] == {"kind": "yanked"}
    assert kinds[("tracing", "1.2.0")] == {"kind": "python"}
    nested = kinds[("zeta-lib", "2.0.0")]
    assert nested["kind"] == "conflict" and nested["dependency"]["name"] == "mid"
    assert set(nested["candidates"]) == {"2.0.0"}
    assert nested["candidates"]["2.0.0"] == {
        "kind": "conflict",
        "dependency": {"name": "core", "spec": "==2.0.0", "extras": [], "marker": ""},
        "chosen": ["core", "1.0.0"],
    }
    assert len(proof.exclusions) == GOLDENS["small"]["exclusions"]


def test_large_proof_covers_the_preferred_set_with_one_clause_each():
    catalog, request, lockfile, proof = fixture("large")
    chosen = dict(proof.chosen)
    expected = set()
    for name, version in proof.chosen:
        for release in catalog.versions(name):
            if release.version > Version.parse(version):
                expected.add((name, str(release.version)))
    assert {(item.name, item.version) for item in proof.exclusions} == expected
    assert len(proof.exclusions) == GOLDENS["large"]["exclusions"] >= 60
    kinds = {item.justification["kind"] for item in proof.exclusions}
    assert {"range", "conflict", "prerelease", "yanked", "python"} <= kinds
    assert any("candidates" in item.justification for item in proof.exclusions)
    assert len(chosen) == GOLDENS["large"]["packages"]


def test_proof_invalid_cause_one_wrong_canonical_order():
    catalog, request, lockfile, proof = fixture("small")
    alphabetical = reproof(proof, chosen=[list(pair) for pair in sorted(proof.chosen)])
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(request, lockfile, alphabetical, catalog)
    assert caught.value.hash == lock_digest(lockfile)
    assert caught.value.reason == "chosen releases are not in canonical order"
    assert str(caught.value) == f"proof rejected for {caught.value.hash}: {caught.value.reason}"
    # A digest computed over an alphabetical document is the same cause at an earlier check.
    body = canonical_document(lockfile)
    body["packages"] = sorted(body["packages"], key=lambda row: row["name"])
    import hashlib

    from depweaver.model import canonical

    wrong_digest = hashlib.sha256(canonical(body).encode()).hexdigest()
    assert wrong_digest != proof.digest
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(request, lockfile, reproof(proof, digest=wrong_digest), catalog)
    assert caught.value.hash == lock_digest(lockfile) != wrong_digest
    assert caught.value.reason == "canonical digest mismatch"


def test_proof_invalid_cause_two_stale_catalog_digest():
    catalog, request, lockfile, proof = fixture("small")
    moved = Repository(catalog.all() + (Release("unrelated", "1.0.0"),))
    assert moved.fingerprint != catalog.fingerprint
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(request, lockfile, proof, moved)
    assert caught.value.hash == lock_digest(lockfile)
    assert caught.value.reason == "catalog digest is stale"
    assert str(caught.value) == f"proof rejected for {caught.value.hash}: catalog digest is stale"


def test_proof_invalid_cause_three_missing_justification_clause():
    catalog, request, lockfile, proof = fixture("small")
    kept = [item.document() for item in proof.exclusions if item.name != "tracing"]
    assert len(kept) == len(proof.exclusions) - 2
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(request, lockfile, reproof(proof, exclusions=kept), catalog)
    assert caught.value.hash == lock_digest(lockfile)
    assert caught.value.reason == "missing justification for tracing 1.1.0"
    # A clause that is present but does not hold is rejected with the same shape.
    forged = []
    for item in proof.exclusions:
        row = item.document()
        if (item.name, item.version) == ("core", "2.0.0"):
            row["justification"] = {
                "kind": "range",
                "parent": None,
                "dependency": {"name": "core", "spec": "<3.0.0", "extras": [], "marker": ""},
            }
        forged.append(row)
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(request, lockfile, reproof(proof, exclusions=forged), catalog)
    assert caught.value.hash == lock_digest(lockfile)
    assert caught.value.reason == "justification does not hold for core 2.0.0"
    # And a clause for a version that is not preferred is rejected too.
    extra = [*(item.document() for item in proof.exclusions), {"name": "core", "version": "0.9.0", "justification": {"kind": "pin"}}]
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(request, lockfile, reproof(proof, exclusions=extra), catalog)
    assert caught.value.reason == "justification for an unselected exclusion core 0.9.0"


def test_the_three_causes_share_one_signature_and_fixing_one_reveals_the_next():
    catalog, request, lockfile, proof = fixture("small")
    moved = Repository(catalog.all() + (Release("unrelated", "1.0.0"),))
    broken = reproof(
        proof,
        chosen=[list(pair) for pair in sorted(proof.chosen)],
        exclusions=[item.document() for item in proof.exclusions if item.name != "toolbelt"],
    )
    signatures = []
    with pytest.raises(ProofInvalid) as first:
        verify_proof(request, lockfile, broken, moved)
    signatures.append(first.value)
    # "Fix" the order only: same type, same hash, same message shape, different reason.
    ordered = reproof(broken, chosen=[list(pair) for pair in canonical_order(lockfile)])
    with pytest.raises(ProofInvalid) as second:
        verify_proof(request, lockfile, ordered, moved)
    signatures.append(second.value)
    # Fix the catalog only: still rejected.
    with pytest.raises(ProofInvalid) as third:
        verify_proof(request, lockfile, ordered, catalog)
    signatures.append(third.value)
    assert {error.hash for error in signatures} == {lock_digest(lockfile)}
    assert all(len(error.hash) == 64 and set(error.hash) <= HEX for error in signatures)
    assert all(str(error).startswith(f"proof rejected for {error.hash}: ") for error in signatures)
    assert [error.reason for error in signatures] == [
        "chosen releases are not in canonical order",
        "catalog digest is stale",
        "missing justification for toolbelt 1.0.0",
    ]
    # Only the proof that addresses all three verifies.
    verify_proof(request, lockfile, prove(catalog, request, lockfile), catalog)


def test_proof_is_bound_to_its_manifest_and_validity():
    catalog, request, lockfile, proof = fixture("small")
    other = Request(request.roots + (Dependency("mid", "*"),), request.target, request.locked)
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(other, lockfile, proof, catalog)
    assert caught.value.reason == "manifest fingerprint mismatch"
    assert caught.value.hash == lock_digest(lockfile)
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(other, lockfile, reproof(proof, manifest=other.fingerprint), catalog)
    assert caught.value.reason.startswith("lockfile does not satisfy manifest: ")


def test_prefer_lowest_reverses_the_preferred_set():
    from depweaver import Policy

    catalog = Repository(
        [
            Release("lib", "1.0.0"),
            Release("lib", "2.0.0"),
            Release("lib", "3.0.0"),
            Release("app", "1.0.0", (Dependency("lib", ">=2"),)),
        ]
    )
    request = Request((Dependency("app"),), policy=Policy(prefer_lowest=True))
    resolution = Resolver(catalog).solve(request)
    assert resolution.versions()["lib"] == "2.0.0"
    proof = prove(catalog, request, resolution)
    assert [(item.name, item.version, item.justification["kind"]) for item in proof.exclusions] == [
        ("lib", "1.0.0", "range")
    ]
    assert proof.exclusions[0].justification["parent"] == ["app", "1.0.0"]
    verify_proof(request, Lockfile(resolution), proof, catalog)


# --- transport ---------------------------------------------------------------


def test_proof_round_trips_through_the_codec(tmp_path):
    catalog, request, lockfile, proof = fixture("large")
    path = tmp_path / "lock.proof.json"
    codec.write(path, proof.document())
    loaded = Proof.load(codec.read(path))
    assert loaded == proof
    assert codec.read(path)["body"]["kind"] == "proof"
    assert codec.read(path)["sha256"] == GOLDENS["large"]["proof_sha256"]
    verify_proof(request, lockfile, loaded, catalog)
    tampered = json.loads(path.read_text())
    tampered["body"]["payload"]["catalog"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        Proof.load(tampered)
    with pytest.raises(ValueError):
        Proof.load(codec.envelope("session", proof.payload()))
    payload = proof.payload()
    payload["exclusions"] = payload["exclusions"][:1] + [{"name": "x", "version": "1.0.0"}]
    with pytest.raises(ValueError):
        Proof.load(codec.envelope("proof", payload))


def test_lockfile_round_trip_keeps_the_digest(tmp_path):
    catalog, request, lockfile, proof = fixture("large")
    path = tmp_path / "lock.json"
    lockfile.write(path)
    again = Lockfile.read(path)
    assert again == lockfile
    assert lock_digest(again) == GOLDENS["large"]["digest"]
    assert [release.name for release in again.resolution.selected] == sorted(
        release.name for release in again.resolution.selected
    )
    assert [pair[0] for pair in canonical_order(again)] != [
        release.name for release in again.resolution.selected
    ]


# --- cache invalidation ----------------------------------------------------------


def test_store_invalidates_cached_resolutions_whose_proof_no_longer_verifies(tmp_path):
    small_catalog, small_request, small_lock, small_proof = fixture("small")
    cyclic_catalog, cyclic_request, cyclic_lock, cyclic_proof = fixture("cyclic")
    store = Store(tmp_path / "store")
    assert store.cached() == ()
    assert store.recall(small_request, small_catalog) is None
    store.remember(small_request, small_lock, small_proof)
    store.remember(cyclic_request, cyclic_lock, cyclic_proof)
    assert store.cached() == tuple(sorted((small_request.fingerprint, cyclic_request.fingerprint)))
    assert store.recall(small_request, small_catalog) == small_lock
    document = codec.read(store.resolution_path(small_request.fingerprint))
    assert document["body"]["kind"] == "cached-resolution"
    assert set(document["body"]["payload"]) == {"manifest", "lock", "proof"}
    moved = Repository(small_catalog.all() + (Release("core", "1.5.0"),))
    assert store.recall(small_request, moved) is None
    assert store.cached() == (cyclic_request.fingerprint,)
    assert not store.resolution_path(small_request.fingerprint).exists()
    # The other entry is untouched by a catalog that is not its own.
    assert store.recall(cyclic_request, cyclic_catalog) == cyclic_lock
    store.remember(small_request, small_lock, small_proof)
    assert store.invalidate(cyclic_catalog) == (small_request.fingerprint,)
    assert store.invalidate(cyclic_catalog) == ()
    assert store.cached() == (cyclic_request.fingerprint,)
    with pytest.raises(ValueError):
        store.remember(cyclic_request, small_lock, small_proof)


def test_store_rejects_a_tampered_cached_proof(tmp_path):
    catalog, request, lockfile, proof = fixture("small")
    store = Store(tmp_path / "store")
    store.remember(request, lockfile, proof)
    alphabetical = reproof(proof, chosen=[list(pair) for pair in sorted(proof.chosen)])
    store.remember(request, lockfile, alphabetical)
    assert store.recall(request, catalog) is None
    assert store.cached() == ()


def test_session_proves_its_records_under_its_own_catalog():
    catalog, request, lockfile, proof = fixture("small")
    session = Session(catalog)
    record = session.solve("small", request)
    assert record.resolution.versions() == lockfile.resolution.versions()
    assert session.prove("small") == proof
    verify_proof(request, Lockfile(record.resolution), session.prove("small"), session.repository)
    session.revise(_revision(catalog, Release("unrelated", "1.0.0")), preserve_records=True)
    revised = session.prove("small")
    assert revised.catalog == session.repository.fingerprint != proof.catalog
    assert revised.digest == proof.digest and revised.chosen == proof.chosen
    with pytest.raises(ProofInvalid) as caught:
        verify_proof(request, Lockfile(record.resolution), revised, catalog)
    assert caught.value.reason == "catalog digest is stale"


def _revision(catalog, release):
    from depweaver.catalog import Editor

    editor = Editor(catalog)
    editor.put(release)
    return editor.commit()


# --- the procedure ------------------------------------------------------------------


def test_relock_and_verify_lock_procedure(tmp_path):
    folder = DATA / "small"
    golden = GOLDENS["small"]
    output = tmp_path / "lock.json"
    arguments = ("--catalog", folder / "catalog.json", "--request", folder / "request.json")

    # Without --canonical the lockfile is written and nothing else.
    plain = run_tool("relock.py", *arguments, "--output", output, cwd=tmp_path)
    assert plain.returncode == 0, plain.stdout + plain.stderr
    assert plain.stdout.splitlines() == [f"lock {output}"]
    assert Lockfile.read(output).resolution.versions() == {
        "app": "1.0.0",
        "core": "1.0.0",
        "toolbelt": "1.1.0",
        "tracing": "1.0.0",
        "zeta-lib": "1.0.0",
    }

    # Skipping the procedure is a stable error, not a pass.
    missing = run_tool("verify_lock.py", *arguments, "--lock", output, cwd=tmp_path)
    assert missing.returncode == 2, missing.stdout + missing.stderr
    assert "tools/relock.py --canonical --prove" in missing.stderr

    # --prove needs --canonical.
    refused = run_tool("relock.py", *arguments, "--output", output, "--prove", cwd=tmp_path)
    assert refused.returncode == 2 and "--prove requires --canonical" in refused.stderr

    # The procedure.
    proved = run_tool(
        "relock.py", *arguments, "--output", output, "--canonical", "--prove", cwd=tmp_path
    )
    assert proved.returncode == 0, proved.stdout + proved.stderr
    lines = proved.stdout.splitlines()
    assert lines[0] == f"lock {output}"
    assert lines[1] == f"digest {golden['digest']}"
    assert lines[2] == f"proof {tmp_path / 'lock.proof.json'}"
    assert lines[3] == f"proof-sha256 {golden['proof_sha256']}"
    digest = lines[1].split()[1]
    assert Proof.load(codec.read(tmp_path / "lock.proof.json")) == Proof.load(
        codec.read(folder / "lock.proof.json")
    )

    verified = run_tool(
        "verify_lock.py", *arguments, "--lock", output, "--expect", digest, cwd=tmp_path
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert verified.stdout.strip() == f"ok {golden['digest']}"

    wrong = run_tool(
        "verify_lock.py", *arguments, "--lock", output, "--expect", "0" * 64, cwd=tmp_path
    )
    assert wrong.returncode == 1
    assert wrong.stdout.strip() == f"digest mismatch: expected {'0' * 64} got {golden['digest']}"

    stale_catalog = tmp_path / "moved.json"
    catalog = Repository.read(folder / "catalog.json")
    codec.write(stale_catalog, Repository(catalog.all() + (Release("unrelated", "1.0.0"),)).document())
    stale = run_tool(
        "verify_lock.py",
        "--catalog",
        stale_catalog,
        "--request",
        folder / "request.json",
        "--lock",
        output,
        cwd=tmp_path,
    )
    assert stale.returncode == 1
    assert stale.stdout.strip() == f"invalid {golden['digest']} catalog digest is stale"


def test_relock_reproduces_the_large_golden_digest(tmp_path):
    folder = DATA / "large"
    output = tmp_path / "large.json"
    proved = run_tool(
        "relock.py",
        "--catalog",
        folder / "catalog.json",
        "--request",
        folder / "request.json",
        "--output",
        output,
        "--canonical",
        "--prove",
        cwd=tmp_path,
    )
    assert proved.returncode == 0, proved.stdout + proved.stderr
    assert f"digest {GOLDENS['large']['digest']}" in proved.stdout.splitlines()
    assert f"proof-sha256 {GOLDENS['large']['proof_sha256']}" in proved.stdout.splitlines()
    verified = run_tool(
        "verify_lock.py",
        "--catalog",
        folder / "catalog.json",
        "--request",
        folder / "request.json",
        "--lock",
        output,
        "--proof",
        tmp_path / "large.proof.json",
        "--expect",
        GOLDENS["large"]["digest"],
        cwd=tmp_path,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert verified.stdout.strip() == f"ok {GOLDENS['large']['digest']}"
