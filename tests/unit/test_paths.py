from __future__ import annotations

from pathlib import Path

from akbench.core.paths import resolve_path, resolve_project_root


def test_resolve_project_root_uses_env_override(tmp_path: Path) -> None:
    override = tmp_path / "elsewhere"
    override.mkdir()
    resolved = resolve_project_root(environ={"AKBENCH_HOME": str(override)})
    assert resolved == override.resolve()


def test_resolve_project_root_finds_marker_ancestor(tmp_path: Path) -> None:
    project = tmp_path / "root" / "ak-bench"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname = "ak-bench"\n', encoding="utf-8")
    nested = project / "src" / "deep"
    nested.mkdir(parents=True)

    assert resolve_project_root(nested, environ={}) == project


def test_resolve_project_root_falls_back_to_start(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert resolve_project_root(plain, environ={}) == plain


def test_resolve_path_expands_relative_against_root(tmp_path: Path) -> None:
    assert resolve_path("data/artifacts", tmp_path) == (tmp_path / "data" / "artifacts").resolve()
    absolute = tmp_path / "absolute"
    assert resolve_path(absolute, tmp_path / "other") == absolute
