"""Shared fixtures for the Atlas repository suite."""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from atlas.config import build as build_config  # noqa: E402
from atlas.store import AtlasBuilder  # noqa: E402


def make_config(**values):
    """A small, fast configuration: three replicas, two shards, few vnodes."""

    settings = {
        "shards": 2,
        "replication_factor": 3,
        "read_consistency": 2,
        "write_consistency": 2,
        "vnodes": 8,
    }
    settings.update(values)
    return build_config(path="none.toml", env={}, values=settings)


@pytest.fixture
def config():
    return make_config()


@pytest.fixture
def store(tmp_path, config):
    return AtlasBuilder().config(config).root(tmp_path / "cluster").build()
