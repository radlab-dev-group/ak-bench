from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def clean_environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """A minimal, deterministic environment for configuration tests."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "AKBENCH_HOME": str(tmp_path / "project"),
    }
    for name in list(os.environ):
        if name.startswith("AKBENCH"):
            monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A scratch directory that resolves as the AK-Bench project root."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "ak-bench"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    return project


@pytest.fixture
def database_url(project_dir: Path) -> str:
    return f"sqlite:///{project_dir / 'test.sqlite'}"


@pytest.fixture
def empty_environ(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Environment with no AKBENCH__ overrides, for loader isolation."""
    for name in list(os.environ):
        if name.startswith("AKBENCH"):
            monkeypatch.delenv(name, raising=False)
    return dict(os.environ)
