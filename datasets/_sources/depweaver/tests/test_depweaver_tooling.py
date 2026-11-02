import base64
import hashlib
import io
import zipfile
from dataclasses import replace

import pytest
from depweaver import (
    Dependency,
    Release,
    Repository,
    Request,
    Resolution,
    Target,
    Version,
    codec,
)
from depweaver.audit import Advisory, Database, audit, summarize
from depweaver.catalog import Editor, Revision, affected, inspect
from depweaver.cli import main
from depweaver.explain import Explanation, feature_sources
from depweaver.inventory import Inventory, package_url, parse_url
from depweaver.lockfile import Lockfile
from depweaver.manifest import Manifest, merge
from depweaver.matrix import Bundle
from depweaver.planner import Installed, Plan, plan
from depweaver.reports import changes, outdated, root_distances, search, statistics, table, tree
from depweaver.requirements import consolidate, format, parse, read
from depweaver.session import Session
from depweaver.store import Index, Store
from depweaver.wheels import Wheel, choose
from depweaver.wheels import inspect as inspect_wheel
from depweaver.workspace import Project, Workspace


@pytest.fixture
def resolved():
    repository = Repository(
        (
            Release("app", "1.0.0", (Dependency("core", "<2"),)),
            Release("core", "1.0.0"),
            Release("core", "2.0.0"),
        )
    )
    request = Request((Dependency("app"),))
    result = Resolution(
        (repository.get("app", "1.0.0"), repository.get("core", "1.0.0")),
        (("app", ()), ("core", ())),
        request.target,
        request.fingerprint,
        repository.fingerprint,
    )
    return repository, request, result


def test_requirements_locations_consolidation_and_roundtrip():
    dependency = parse('Some_Pkg[fast,ssl] >=1,<3; python_version >= "3.10"')
    assert parse(format(dependency)) == dependency
    records = read(
        "\n".join(("# header", "a >=1, " + chr(92), " <3 # comment", 'b; sys_platform == "linux"')),
        "deps.txt",
    )
    assert [record.line for record in records] == [2, 4]
    assert records[0].dependency.spec.matches(Version.parse("2.0.0"))
    merged = consolidate((parse("a[fast] >=1"), parse("a[ssl] <2")))
    assert len(merged) == 1 and merged[0].extras == {"fast", "ssl"}
    assert not merged[0].spec.matches(Version.parse("2.0.0"))
    with pytest.raises(ValueError, match="directives"):
        read("-r other.txt")


def test_manifest_profiles_and_workspace_merge():
    manifest = Manifest.load(
        {
            "name": "demo",
            "dependencies": ["app"],
            "groups": {"test": ["core<2"]},
            "profiles": {"linux": {"groups": ["test"], "target": {"sys_platform": "linux"}}},
        }
    )
    assert len(manifest.request("linux").roots) == 2
    combined = merge((manifest,))
    assert Manifest.load(combined.document()).fingerprint == combined.fingerprint
    assert len(combined.request("demo-linux").roots) == 2
    with pytest.raises(ValueError, match="collide"):
        merge((manifest, manifest))


def test_request_codec_strictness_and_duplicate_json_keys(tmp_path, resolved):
    _repository, request, _result = resolved
    assert codec.request(request.document()) == request
    with pytest.raises(ValueError, match="booleans"):
        codec.request({"roots": [], "policy": {"allow_yanked": 1}})
    with pytest.raises(ValueError, match="unknown"):
        codec.request({"roots": [], "mystery": True})
    path = tmp_path / "bad.json"
    path.write_text('{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match="duplicate"):
        codec.read(path)
    document = codec.envelope("example", {"answer": 42})
    codec.write(path, document)
    assert codec.unwrap(codec.read(path), "example") == {"answer": 42}


def test_catalog_revisions_are_reversible_and_preconditions_are_atomic(resolved):
    repository, _request, _result = resolved
    editor = Editor(repository)
    editor.yank("core", "2.0.0")
    editor.put(Release("extra", "1.0.0"))
    revision = Revision.load(editor.commit().document())
    changed = revision.apply(repository)
    assert changed.get("core", "2.0.0").yanked
    assert revision.inverse().apply(changed).fingerprint == repository.fingerprint
    assert repository.get("core", "2.0.0").yanked is False
    with pytest.raises(ValueError, match="stale"):
        revision.apply(changed)
    assert affected(repository, ("core",)) == ("app", "core")
    broken = Repository((Release("app", "1.0.0", (Dependency("missing"),)),))
    assert inspect(broken)[0].code == "absent-package"


def test_session_roundtrip_replay_and_atomic_batch(resolved):
    repository, request, _result = resolved
    session = Session(repository)
    session.solve("base", request)
    restored = Session.load(session.document())
    assert restored.replay() == ()
    before = session.document()
    batch = session.batch({"a-good": request, "z-bad": Request((Dependency("missing"),))})
    assert not batch.ok and not batch.committed
    assert session.document() == before
    session.drop(("base",))
    assert not session.records


def test_workspace_lock_publication_roundtrip_and_failed_updates(tmp_path, resolved):
    repository, _request, result = resolved
    project = Project("demo", Manifest.load({"name": "demo", "dependencies": ["app"]}))
    workspace = Workspace(repository, (project,))
    assert workspace.solve().ok
    path = tmp_path / "workspace.json"
    workspace.save(path)
    restored = Workspace.read(path)
    assert restored.status() == workspace.status()
    assert Bundle.load(restored.bundle().document()).common() == result.versions()
    restored.configure(
        replace(project, manifest=Manifest.load({"name": "demo", "dependencies": ["missing"]}))
    )
    assert not restored.solve().committed
    assert not restored.locks


def test_inventory_plans_and_explanations(resolved):
    repository, request, result = resolved
    inventory = Inventory.from_resolution(result)
    assert Inventory.load(inventory.document(), repository) == inventory
    assert parse_url(package_url("Some_Package", "1.0.0+build")) == ("some-package", "1.0.0+build")
    installed = Installed()
    transition = Plan.load(plan(installed, result).document())
    after = transition.apply(installed)
    assert transition.inverse().apply(after) == installed
    explanation = Explanation(repository, request, result)
    assert explanation.path("core") == ("app", "core")
    assert explanation.alternatives("core")[0].reasons == ("requirement",)
    assert feature_sources(request, result) == {}
    assert inventory.compare(inventory)["changed"] == []


def test_offline_advisories_and_reports(resolved):
    repository, request, result = resolved
    database = Database((Advisory("D-1", "core", "<2", "high", "old core"),))
    findings = audit(repository, result, Database.load(database.document()), roots=("app",))
    assert findings[0].safe_versions == ("2.0.0",)
    assert findings[0].paths == (("app", "core"),)
    assert summarize(findings)["count"] == 1
    assert statistics(result)["packages"] == 2
    assert root_distances(result, ("app",)) == {"app": 0, "core": 1}
    assert "core 1.0.0" in tree(result)
    assert "Required by" in table(result, request)
    assert outdated(repository, result)[0]["latest"] == "2.0.0"
    assert len(search(repository, "core", ">=2")) == 1
    assert changes(result, result)["impacted"] == []


def test_artifact_store_immutable_publication_indexes_and_corruption(tmp_path):
    store = Store(tmp_path / "store")
    entry = store.put(b"example", "example.whl")
    assert store.put(b"example", "example.whl") == entry
    index = Index((entry,))
    store.publish("main", index)
    assert store.index("main") == index
    orphan = store.put(b"unused", "other.whl")
    assert store.collect((index,)) == (orphan.digest,)
    assert store.path(orphan.digest).exists()
    store.collect((index,), dry_run=False)
    assert not store.path(orphan.digest).exists()
    store.path(entry.digest).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        store.get(entry)


def make_wheel(path):
    files = {
        "demo/__init__.py": b"VALUE = 1\n",
        "demo-1.0.0.dist-info/METADATA": b"Name: demo\nVersion: 1.0.0\n",
    }
    record = "demo-1.0.0.dist-info/RECORD"
    lines = []
    for name, data in files.items():
        checksum = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        lines.append(f"{name},sha256={checksum},{len(data)}")
    files[record] = ("\n".join((*lines, record + ",,")) + "\n").encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def test_wheel_compatibility_archive_record_and_store(tmp_path):
    universal = Wheel.parse("demo-1.0.0-py3-none-any.whl")
    native = Wheel.parse("demo-1.0.0-cp312-cp312-linux_x86_64.whl")
    assert choose((universal, native), Target(), "demo", Version.parse("1.0.0")) == native
    path = tmp_path / universal.filename
    make_wheel(path)
    report = inspect_wheel(path)
    assert "Name: demo" in report.metadata
    store = Store(tmp_path / "store")
    assert store.verify_wheel(store.import_file(path)).sha256 == report.sha256
    with pytest.raises(ValueError, match="checksum"):
        inspect_wheel(path, expected_digest="0" * 64)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("../escape", b"x")
    path.write_bytes(raw.getvalue())
    with pytest.raises(ValueError, match="unsafe"):
        inspect_wheel(path)


def test_cli_solve_verify_inspect_and_error_codes(tmp_path, capsys, resolved):
    repository, request, result = resolved
    index, query, lock = (tmp_path / name for name in ("repo.json", "request.json", "lock.json"))
    codec.write(index, repository.document())
    codec.write(query, request.document())
    assert main(["solve", str(index), "--request", str(query), "--output", str(lock)]) == 0
    assert Lockfile.read(lock).resolution == result
    assert main(["verify", str(index), str(query), str(lock)]) == 0
    assert main(["inspect", str(index)]) == 0
    codec.write(query, Request((Dependency("missing"),)).document())
    assert main(["solve", str(index), "--request", str(query)]) == 1
    assert "Cannot resolve" in capsys.readouterr().err


def test_metadata_headers_roundtrip_and_batch_failures(resolved):
    from depweaver.metadata import export_batch, export_metadata, import_batch, import_metadata

    repository, _request, _result = resolved
    original = repository.get("app", "1.0.0")
    text = export_metadata(original, summary="Application")
    imported = import_metadata(text)
    assert imported.release == original
    assert imported.summary == "Application"
    assert import_batch(export_batch(repository)).repository().fingerprint == repository.fingerprint
    failed = import_batch({"a": text, "b": text, "bad": "Name: invalid\n\n"})
    assert len(failed.imported) == 1 and len(failed.failures) == 2
    with pytest.raises(ValueError, match="invalid sources"):
        failed.repository()
    with pytest.raises(ValueError, match="duplicate"):
        import_metadata(text.replace("Name: app", "Name: app\nName: app"))


def test_minimal_root_conflicts_and_conservative_update_impact(resolved):
    from depweaver.constraints import Analyzer, intersect_roots, update_impact

    repository, request, result = resolved
    analyzer = Analyzer(repository)
    assert analyzer.direct_domains(request)["app"]["accepted"] == ["1.0.0"]
    conflict = Request((Dependency("core", "<2"), Dependency("core", ">=2"), Dependency("app")))
    core = analyzer.core(conflict)
    assert core.minimal and len(core.roots) == 2
    assert analyzer.trial(Request(core.roots)).satisfiable is False
    for index in range(len(core.roots)):
        assert (
            analyzer.trial(Request(core.roots[:index] + core.roots[index + 1 :])).satisfiable
            is True
        )
    assert not analyzer.core(conflict, max_trials=1).minimal
    assert len(intersect_roots(Request((Dependency("core", ">=1"), Dependency("core", "<2"))))) == 1
    impact = update_impact(result, frozenset({"core"}))
    assert impact.dependents == ("app", "core")
    assert impact.retained_pins == (("app", "1.0.0"),)
