"""The engine boundary: one protocol, two engines, the same answers.

Every test imports the engine package inside the test body on purpose. A
module-level import of a package the agent has not written would stop
collection, and a collection error says nothing about the work; a failing
test does.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from atlas.config import build
from atlas.values import Record


def _workspace_root() -> Path:
    """The root of the checkout under test.

    Hidden tests are copied into the workspace at evaluation time and one
    directory deeper when the dataset validator verifies a mutation, so the
    root is found by walking up to the project marker rather than counting
    directories.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    raise AssertionError("the checkout under test was not found")


def _root() -> Path:
    return _workspace_root()


def _engines():
    import atlas.engines as engines

    return engines


def _config(**overrides):
    values = dict(node_id="atlas-0", epoch=1, shards=2, vnodes=64,
                  replication_factor=3, write_consistency=2)
    values.update(overrides)
    return build(values=values)


def _memory_engine():
    return _engines().MemoryStorageEngine()


def _disk_engine(tmp_path: Path):
    return _engines().DiskStorageEngine(tmp_path / "shard-0")


# -- the protocol ------------------------------------------------------------


def test_the_protocol_is_runtime_checkable_and_names_the_five_operations():
    engines = _engines()
    protocol = engines.StorageEngine
    assert getattr(protocol, "__runtime_protocol__", False), (
        "StorageEngine must be a runtime_checkable Protocol, so a caller can ask an object whether it is an engine"
    )
    for name in ("get", "put", "scan", "compact", "flush"):
        assert callable(getattr(protocol, name, None)), f"StorageEngine declares no {name}()"


@pytest.mark.parametrize("kind", ["memory", "disk"])
def test_an_engine_satisfies_the_protocol(kind, tmp_path):
    engines = _engines()
    engine = _memory_engine() if kind == "memory" else _disk_engine(tmp_path)
    assert isinstance(engine, engines.StorageEngine), f"{kind} engine is not a StorageEngine"


@pytest.mark.parametrize("kind", ["memory", "disk"])
def test_the_engine_contract(kind, tmp_path):
    engine = _memory_engine() if kind == "memory" else _disk_engine(tmp_path)

    first = Record.put("alpha", {"v": 1}, generation=1, writer="atlas-0")
    assert engine.put(first) is True, "storing a new record changed nothing"
    assert engine.get("alpha") == first
    assert engine.get("nope") is None
    assert engine.put(first) is False, "putting the same record again changed something"

    second = Record.put("alpha", {"v": 2}, generation=2, writer="atlas-0")
    assert engine.put(second) is True
    assert engine.get("alpha").value == {"v": 2}

    for _ in range(2):
        engine.compact()
        engine.flush()
    assert engine.get("alpha") == second, "compact/flush changed a stored record"


@pytest.mark.parametrize("kind", ["memory", "disk"])
def test_scan_is_ascending_and_half_open(kind, tmp_path):
    engine = _memory_engine() if kind == "memory" else _disk_engine(tmp_path)
    for key, generation in (("a", 1), ("b", 1), ("c", 1), ("d", 1)):
        engine.put(Record.put(key, {"k": key}, generation=generation, writer="atlas-0"))

    assert [record.key for record in engine.scan()] == ["a", "b", "c", "d"]
    assert [record.key for record in engine.scan("b", "d")] == ["b", "c"], (
        "scan is [low, high): the upper bound is excluded"
    )
    assert [record.key for record in engine.scan(low="c")] == ["c", "d"]
    assert [record.key for record in engine.scan(high="b")] == ["a"]


# -- the store on top of it ---------------------------------------------------


@pytest.mark.parametrize("kind", ["memory", "disk"])
def test_the_store_takes_an_engine(kind, tmp_path):
    from atlas.store import Atlas

    store = Atlas(config=_config(), root=tmp_path / kind, engine=kind)
    result = store.put("widget", {"n": 1})
    assert store.get("widget").value == {"n": 1}
    assert result.record.generation == 1
    assert store.current_generation("widget") == 1

    store.put("widget", {"n": 2})
    assert store.get("widget").value == {"n": 2}
    assert store.current_generation("widget") == 2

    store.delete("widget")
    assert store.get("widget") is None


def test_the_default_engine_is_the_disk_one_and_a_shard_shows_its_engine(tmp_path):
    engines = _engines()
    from atlas.store import Atlas

    store = Atlas(config=_config(), root=tmp_path / "default")
    store.put("widget", {"n": 1})
    shard = store.shard_of("widget")
    engine = store.nodes["atlas-1"].store(shard).engine
    assert isinstance(engine, engines.DiskStorageEngine), (
        "a store built without an engine is on the disk engine"
    )


def test_both_engines_agree_on_the_same_workload(tmp_path):
    from atlas.store import Atlas

    def run(kind: str) -> list:
        store = Atlas(config=_config(), root=tmp_path / kind, engine=kind)
        seen = []
        for index in range(6):
            store.put(f"key-{index}", {"i": index})
            seen.append((store.get(f"key-{index}").value, store.current_generation(f"key-{index}")))
        store.put("shared", {"first": True})
        store.put("shared", {"second": True})
        seen.append(store.get("shared").value)
        store.delete("key-2")
        seen.append(store.get("key-2"))
        seen.append(sorted(store.current_generation(f"key-{index}") for index in range(6)))
        return seen

    assert run("memory") == run("disk"), "the two engines answer the same workload differently"


def test_an_engine_instance_can_be_injected(tmp_path):
    engines = _engines()
    from atlas.store import Atlas

    store = Atlas(
        config=_config(),
        root=tmp_path / "injected",
        engine=engines.MemoryStorageEngine(),
    )
    store.put("widget", {"n": 1})
    assert store.get("widget").value == {"n": 1}


# -- the repository suite is the behaviour being preserved --------------------


def test_the_repository_suite_still_passes(tmp_path):
    root = _root()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
