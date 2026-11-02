from depweaver import Dependency, Release, Repository, Request, Resolver


def test_backtracking_finds_the_lower_compatible_release():
    repository = Repository(
        [
            Release("app", "2.0.0", (Dependency("core", "==2"),)),
            Release("app", "1.0.0", (Dependency("core", "==1"),)),
            Release("core", "1.0.0"),
            Release("core", "2.0.0"),
        ]
    )
    result = Resolver(repository).solve(Request((Dependency("app"), Dependency("core", "==1"))))
    assert result.versions() == {"app": "1.0.0", "core": "1.0.0"}


def test_two_requested_extras_activate_both_dependency_sets():
    repository = Repository(
        [
            Release(
                "app",
                "1.0.0",
                (
                    Dependency("fast", marker='extra == "fast"'),
                    Dependency("safe", marker='extra == "safe"'),
                ),
                extras=frozenset({"fast", "safe"}),
            ),
            Release("fast", "1.0.0"),
            Release("safe", "1.0.0"),
        ]
    )
    result = Resolver(repository).solve(
        Request(
            (
                Dependency("app", extras=frozenset({"fast"})),
                Dependency("app", extras=frozenset({"safe"})),
            )
        )
    )
    assert set(result.versions()) == {"app", "fast", "safe"}
