"""Independent regression witnesses, exhaustive oracle and stress families."""

import itertools
import json
import os
import random
import subprocess
import sys

import pytest
from depweaver import (
    Dependency,
    Policy,
    Release,
    Repository,
    Request,
    Resolver,
    SearchLimit,
    Target,
    Unsatisfiable,
    Version,
)
from depweaver.errors import Conflict
from depweaver.learning import Learner
from depweaver.lockfile import Lockfile
from depweaver.trail import Trail
from depweaver.validation import validate


def release(name, version=1, dependencies=(), **options):
    return Release(name, f"{version}.0.0", tuple(dependencies), **options)


def assert_valid(repository, request, result):
    assert validate(repository, request, result) == ()
    assert result.selected == tuple(sorted(result.selected, key=lambda item: item.name))


def test_regression_01_rollback_discards_every_abandoned_decision():
    repository = Repository(
        [
            release("app", 2, [Dependency("core", "==2")]),
            release("app", 1, [Dependency("core", "==1")]),
            release("core", 1),
            release("core", 2),
        ]
    )
    request = Request((Dependency("app"), Dependency("core", "==1")))
    solver = Resolver(repository)
    result = solver.solve(request)
    assert result.versions() == {"app": "1.0.0", "core": "1.0.0"}
    assert solver.statistics.conflicts > 0
    trail = Trail()
    trail.assign(release("first"))
    saved = trail.level
    trail.assign(release("second"))
    trail.assign(release("third"))
    trail.rollback(saved)
    assert set(trail.selected) == {"first"}
    assert len(trail.decisions) == 1


def test_regression_02_late_feature_activation_reexpands_an_existing_release():
    repository = Repository(
        [
            release(
                "a",
                dependencies=[Dependency("driver", marker='extra == "gpu"')],
                extras=frozenset({"gpu"}),
            ),
            release("b", dependencies=[Dependency("a", extras=frozenset({"gpu"}))]),
            release("driver"),
        ]
    )
    request = Request((Dependency("a"), Dependency("b")))
    result = Resolver(repository).solve(request)
    assert set(result.versions()) == {"a", "b", "driver"}
    assert dict(result.extras)["a"] == ("gpu",)
    assert_valid(repository, request, result)


def test_regression_03_feature_union_is_commutative_and_complete():
    repository = Repository(
        [
            release(
                "app",
                dependencies=[
                    Dependency("fast-lib", marker='extra == "fast"'),
                    Dependency("safe-lib", marker='extra == "safe"'),
                ],
                extras=frozenset({"fast", "safe"}),
            ),
            release("fast-lib"),
            release("safe-lib"),
        ]
    )
    roots = (
        Dependency("app", extras=frozenset({"fast"})),
        Dependency("app", extras=frozenset({"safe"})),
    )
    documents = []
    for ordering in (roots, roots[::-1]):
        request = Request(ordering)
        result = Resolver(repository).solve(request)
        assert_valid(repository, request, result)
        assert dict(result.extras)["app"] == ("fast", "safe")
        documents.append(result.document())
    assert documents[0] == documents[1]


def test_regression_04_markers_use_the_declaring_packages_features():
    repository = Repository(
        [
            release(
                "app",
                dependencies=[Dependency("child", marker='extra == "gpu"')],
                extras=frozenset({"gpu"}),
            ),
            release("child"),
        ]
    )
    request = Request((Dependency("app", extras=frozenset({"gpu"})),))
    result = Resolver(repository).solve(request)
    assert result.versions() == {"app": "1.0.0", "child": "1.0.0"}
    assert_valid(repository, request, result)


def test_regression_05_learned_clause_keeps_all_contextual_decisions():
    repository = Repository(
        [
            release("a", 2, [Dependency("core", "==2")]),
            release("a", 1, [Dependency("core", "==1")]),
            release("b", 2, [Dependency("core", "==1")]),
            release("b", 1, [Dependency("core", "==2")]),
            release("core", 1),
            release("core", 2),
        ]
    )
    request = Request((Dependency("a"), Dependency("b")))
    solver = Resolver(repository)
    result = solver.solve(request)
    assert result.versions() == {"a": "2.0.0", "b": "1.0.0", "core": "2.0.0"}
    assert solver.learner.clauses
    learner = Learner()
    clause = frozenset({("a", "2.0.0"), ("b", "2.0.0")})
    learner.learn(Conflict("core", "incompatible parents", clause))
    assert learner.violated(frozenset({("a", "2.0.0")})) is None
    assert learner.violated(clause) == clause


def test_regression_06_failed_request_does_not_poison_a_different_target():
    repository = Repository(
        [
            release("app", 2, [Dependency("core", "==2", marker='sys_platform == "linux"')]),
            release("core", 1),
            release("core", 2),
        ]
    )
    roots = (Dependency("app"), Dependency("core", "==1"))
    solver = Resolver(repository)
    with pytest.raises(Unsatisfiable):
        solver.solve(Request(roots, Target(sys_platform="linux")))
    assert solver.learner.clauses
    request = Request(roots, Target(sys_platform="win32"))
    result = solver.solve(request)
    assert result.versions() == {"app": "2.0.0", "core": "1.0.0"}
    assert_valid(repository, request, result)


def test_regression_07_candidate_cache_distinguishes_target_and_feature_context():
    repository = Repository(
        [
            release("app", 2, requires_python=">=3.12", extras=frozenset()),
            release("app", 1, requires_python=">=3.10", extras=frozenset({"gpu"})),
        ]
    )
    solver = Resolver(repository)
    first = Request((Dependency("app"),), Target("3.12.0"))
    assert solver.solve(first).versions()["app"] == "2.0.0"
    for request in (
        Request((Dependency("app"),), Target("3.11.0")),
        Request((Dependency("app", extras=frozenset({"gpu"})),), Target("3.12.0")),
    ):
        result = solver.solve(request)
        assert result.versions()["app"] == "1.0.0"
        assert_valid(repository, request, result)
    solver.solve(first)
    assert solver.cache.hits > 0


def test_regression_08_partial_update_keeps_every_unrequested_pin():
    repository = Repository(
        [
            release("app", 1, [Dependency("core", ">=1")]),
            release("app", 2, [Dependency("core", ">=1")]),
            release("core", 1),
            release("core", 2),
        ]
    )
    request = Request(
        (Dependency("app"),),
        locked=(("app", "1.0.0"), ("core", "1.0.0")),
        update=frozenset({"app"}),
    )
    result = Resolver(repository).solve(request)
    assert result.versions() == {"app": "2.0.0", "core": "1.0.0"}
    assert_valid(repository, request, result)


def exhaustive(repository, request):
    """Enumerate complete assignments; do not call production propagation/cache."""
    names = repository.names()
    choices = [(None, *repository.versions(name)) for name in names]
    for values in itertools.product(*choices):
        selected = {
            name: value for name, value in zip(names, values, strict=True) if value is not None
        }
        required, extras = {}, {}
        for root in request.roots:
            if root.marker.matches(request.target):
                required.setdefault(root.name, []).append(root)
                extras[root.name] = extras.get(root.name, frozenset()) | root.extras
        processed = set()
        while True:
            pending = [
                (name, extras.get(name, frozenset())) for name in required if name in selected
            ]
            pending = [item for item in pending if item not in processed]
            if not pending:
                break
            for name, features in pending:
                processed.add((name, features))
                for dependency in selected[name].dependencies:
                    if dependency.marker.matches(request.target, features):
                        rows = required.setdefault(dependency.name, [])
                        if dependency not in rows:
                            rows.append(dependency)
                        extras[dependency.name] = (
                            extras.get(dependency.name, frozenset()) | dependency.extras
                        )
        if set(selected) != set(required):
            continue
        valid = True
        for name, version in selected.items():
            requirements = required[name]
            locked = dict(request.locked).get(name)
            same_pin = locked is not None and version.version == Version.parse(locked)
            valid = valid and all(
                dependency.spec.matches(version.version) for dependency in requirements
            )
            valid = valid and extras.get(name, frozenset()) <= version.extras
            valid = valid and version.requires_python.matches(
                Version.coerce(request.target.python_version)
            )
            if locked and name not in request.update:
                valid = valid and same_pin
            if version.yanked and not request.policy.allow_yanked and not same_pin:
                valid = False
            if version.version.prerelease and not request.policy.allow_prerelease and not same_pin:
                valid = valid and any(
                    dependency.spec.allows_prerelease for dependency in requirements
                )
        if valid:
            yield {name: str(value.version) for name, value in selected.items()}


@pytest.mark.parametrize("seed", range(60))
def test_generated_small_repositories_agree_with_exhaustive_oracle(seed):
    randomizer = random.Random(seed)
    names = ["a", "b", "c", "d"]
    releases = []
    for name in names:
        for version in (1, 2, 3):
            dependencies = []
            for target in names:
                if target != name and randomizer.randrange(5) == 0:
                    spec = randomizer.choice(["*", "==1", ">=2", "<3", "!=2"])
                    marker = randomizer.choice(
                        ["", 'extra == "feature"', 'sys_platform == "linux"']
                    )
                    features = (
                        frozenset({"feature"}) if randomizer.randrange(3) == 0 else frozenset()
                    )
                    dependencies.append(Dependency(target, spec, features, marker))
            releases.append(release(name, version, dependencies, extras=frozenset({"feature"})))
    repository = Repository(releases)
    roots = tuple(
        Dependency(
            name,
            randomizer.choice(["*", ">=2", "==1"]),
            frozenset({"feature"}) if randomizer.randrange(2) else frozenset(),
        )
        for name in names[:2]
    )
    request = Request(roots, Target(sys_platform=randomizer.choice(["linux", "win32"])))
    answers = list(exhaustive(repository, request))
    solver = Resolver(repository)
    before = repository.document()
    try:
        result = solver.solve(request)
    except Unsatisfiable:
        assert not answers, (seed, answers)
    else:
        assert result.versions() in answers, (seed, result.versions(), answers)
        assert_valid(repository, request, result)
        reversed_repository = Repository(reversed(releases))
        assert (
            Resolver(reversed_repository)
            .solve(Request(tuple(reversed(roots)), request.target))
            .versions()
            == result.versions()
        )
    assert repository.document() == before


def test_cycles_and_recursive_feature_growth_terminate_with_complete_closure():
    repository = Repository(
        [
            release(
                "a",
                dependencies=[Dependency("b", extras=frozenset({"feature"}))],
                extras=frozenset({"feature"}),
            ),
            release(
                "b",
                dependencies=[
                    Dependency("a", extras=frozenset({"feature"})),
                    Dependency("leaf", marker='extra == "feature"'),
                ],
                extras=frozenset({"feature"}),
            ),
            release("leaf"),
        ]
    )
    request = Request((Dependency("a"),))
    result = Resolver(repository).solve(request)
    assert set(result.versions()) == {"a", "b", "leaf"}
    assert_valid(repository, request, result)


@pytest.mark.parametrize(
    "roots",
    [
        (Dependency("missing"),),
        (Dependency("a", extras=frozenset({"unsupported"})),),
        (Dependency("a", ">3,<1"),),
    ],
)
def test_unsatisfiable_requests_have_structured_explanations(roots):
    solver = Resolver(Repository([release("a")]))
    with pytest.raises(Unsatisfiable) as caught:
        solver.solve(Request(roots))
    assert caught.value.conflict.reason
    assert caught.value.conflict.document()["package"]
    assert solver.solve(Request((Dependency("a"),))).versions() == {"a": "1.0.0"}


def test_yanked_prerelease_and_python_eligibility_are_separate_from_ranges():
    repository = Repository(
        [
            Release("app", "3.0.0-beta.1"),
            Release("app", "2.0.0", yanked=True),
            Release("app", "1.0.0"),
        ]
    )
    solver = Resolver(repository)
    assert solver.solve(Request((Dependency("app"),))).versions() == {"app": "1.0.0"}
    assert solver.solve(
        Request((Dependency("app"),), policy=Policy(allow_prerelease=True))
    ).versions() == {"app": "3.0.0-beta.1"}
    assert solver.solve(Request((Dependency("app"),), locked=(("app", "2.0.0"),))).versions() == {
        "app": "2.0.0"
    }


def test_large_independent_domains_do_not_require_cartesian_enumeration():
    releases = []
    for index in range(28):
        name = f"package-{index:02d}"
        for version in range(1, 16):
            releases.append(release(name, version))
    repository = Repository(releases)
    request = Request(
        tuple(Dependency(f"package-{index:02d}") for index in range(28)),
        policy=Policy(max_decisions=40),
    )
    solver = Resolver(repository)
    result = solver.solve(request)
    assert len(result.selected) == 28
    assert all(version == "15.0.0" for version in result.versions().values())
    assert solver.statistics.decisions == 28


def test_search_limit_is_not_reported_as_unsatisfiable():
    repository = Repository([release("a"), release("b")])
    with pytest.raises(SearchLimit):
        Resolver(repository).solve(
            Request((Dependency("a"), Dependency("b")), policy=Policy(max_decisions=1))
        )


def test_resolution_and_lock_are_reproducible_in_a_fresh_process(tmp_path):
    repository = Repository([release("a", 1, [Dependency("b")]), release("b")])
    request = Request((Dependency("a"),))
    expected = Resolver(repository).solve(request)
    path = tmp_path / "repository.json"
    path.write_text(json.dumps(repository.document()))
    script = "\n".join(
        (
            "import json, sys",
            "from depweaver import Dependency, Repository, Request, Resolver",
            "repo = Repository.load(json.load(open(sys.argv[1])))",
            "result = Resolver(repo).solve(Request((Dependency('a'),)))",
            "print(json.dumps(result.document(), sort_keys=True))",
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        text=True,
        check=True,
        env=os.environ.copy(),
        timeout=20,
    )
    assert json.loads(completed.stdout) == expected.document()
    assert Lockfile.load(Lockfile(expected).document()).resolution == expected
