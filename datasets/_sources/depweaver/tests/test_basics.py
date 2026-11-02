import pytest
from depweaver import (
    Dependency,
    Marker,
    Release,
    Repository,
    Request,
    Resolver,
    Spec,
    Target,
    Version,
)
from depweaver.graph import Graph
from depweaver.lockfile import Lockfile
from depweaver.validation import validate


def test_semantic_prerelease_order():
    ordered = ["1.0.0-alpha", "1.0.0-alpha.2", "1.0.0-alpha.10", "1.0.0-beta", "1.0.0"]
    assert sorted(map(Version.parse, reversed(ordered))) == list(map(Version.parse, ordered))
    assert Version.parse("1.0.0+first") == Version.parse("1.0.0+second")


@pytest.mark.parametrize(
    "spec,accepted,rejected",
    [
        ("^1.2", "1.9.0", "2.0.0"),
        ("^0.2.3", "0.2.9", "0.3.0"),
        ("~1.2", "1.2.9", "1.3.0"),
        ("1.*", "1.5.0", "2.0.0"),
        (">=1,<3,!=2", "1.5.0", "2.0.0"),
        ("==1 || ==3", "3.0.0", "2.0.0"),
    ],
)
def test_version_specs(spec, accepted, rejected):
    parsed = Spec.parse(spec)
    assert parsed.matches(Version.parse(accepted))
    assert not parsed.matches(Version.parse(rejected))


def test_marker_boolean_precedence_and_python_comparison():
    marker = Marker('python_version >= "3.10" and (sys_platform == "linux" or extra == "gpu")')
    assert marker.matches(Target("3.12.0", "linux"))
    assert marker.matches(Target("3.12.0", "win32"), frozenset({"gpu"}))
    assert not marker.matches(Target("3.9.0", "linux"))


def test_straight_line_resolution_graph_and_lock_roundtrip(tmp_path):
    repository = Repository(
        [
            Release("app", "1.0.0", (Dependency("core", ">=1"),)),
            Release("core", "1.0.0"),
            Release("core", "2.0.0"),
        ]
    )
    request = Request((Dependency("app"),))
    result = Resolver(repository).solve(request)
    assert result.versions() == {"app": "1.0.0", "core": "2.0.0"}
    assert validate(repository, request, result) == ()
    assert Graph.from_resolution(result).shortest_path("app", "core") == ("app", "core")
    path = tmp_path / "lock.json"
    Lockfile(result).write(path)
    assert Lockfile.read(path).resolution == result


def test_metadata_roundtrip_and_name_normalization():
    repository = Repository([Release("Some_Package", "1.0.0")])
    assert repository.names() == ("some-package",)
    assert Repository.load(repository.document()).fingerprint == repository.fingerprint
