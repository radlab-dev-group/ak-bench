"""The service modules: configuration, the registries, the schema, and retention."""

from atlas.cache import ReadCache
from atlas.config import ConfigError, explain
from atlas.registry import UnknownStrategyError
from atlas.registry import STRATEGIES
from atlas.retention import Retention
from atlas.schema import discover
from atlas.values import Record
from atlas.vclock import VersionVector


def test_the_five_configuration_layers_keep_their_precedence(tmp_path):
    from atlas.config import build

    path = tmp_path / "c.toml"
    path.write_text("shards = 3\n[profile.small]\nshards = 5\n", encoding="utf-8")
    config = build(path=path, env={"ATLAS_SHARDS": "7"})
    assert config["shards"] == 7
    assert config.source_of("shards") == "env:ATLAS_SHARDS"
    config = build(path=path, env={}, profile="small")
    assert config["shards"] == 5
    assert config.source_of("shards") == "profile:small"
    config = build(path=path, env={})
    assert config["shards"] == 3
    assert config.source_of("shards") == "file"


def test_a_quorum_inequality_is_refused_at_build_time():
    from atlas.config import build

    try:
        build(path="none.toml", env={}, values={"read_consistency": 1, "write_consistency": 1})
    except ConfigError as caught:
        assert "exceed" in str(caught)
    else:
        raise AssertionError("an impossible quorum must be refused")


def test_an_unknown_strategy_name_is_an_error_at_dispatch():
    from atlas.config import build

    config = build(path="none.toml", env={})
    try:
        STRATEGIES.resolve_conflict("no-such-strategy")
    except UnknownStrategyError as caught:
        assert "desc-writer" in str(caught)
    else:
        raise AssertionError("an unregistered strategy name must not dispatch")


def test_a_registered_strategy_dispatches():
    resolve = STRATEGIES.resolve_conflict("desc-writer")
    assert callable(resolve)


def test_a_strategy_is_registered_exactly_once():
    from atlas.registry import StrategySet

    fresh = StrategySet()
    factory = lambda: (lambda: None)
    fresh.conflict.register("x", factory)
    try:
        fresh.conflict.register("x", factory)
    except ConfigError:
        pass
    else:
        raise AssertionError("re-registration must be refused, not a silent overwrite")


def test_the_schema_reads_and_the_schema_writes_in_opposite_directions():
    schema = discover()
    assert schema.version == 3
    assert schema.reader_accepts("v2")
    assert schema.reader_accepts("v1")
    assert schema.writer_emits() == "v3"


def test_the_generated_tables_match_the_schema_document():
    import atlas.tables as tables
    from atlas.schema import discover

    schema = discover()
    for column in schema.columns:
        generated = tables.column(column.name)
        assert generated[1] == column.type
        assert generated[3] == column.width
    assert tables.READER_ACCEPTS == ("v1", "v2", "v3")
    assert tables.WRITER_EMITS == f"v{schema.version}"


def test_the_generated_file_declares_that_it_is_generated():
    from atlas import tables

    source = tables.__doc__ or ""
    assert "GENERATED" in source.upper()


def test_retention_drops_only_the_old_tombstones(tmp_path):
    from atlas.storage import ShardStorage

    store = ShardStorage(tmp_path / "s", 0)
    store.put("a", 1, writer="n")
    store.delete("a", writer="n")
    rec = store.resolve("a")
    store.put("b", 1, writer="n")
    retention = Retention(grace_ms=0)
    report = retention.sweep_store(store, now_ms=rec.written_at + 1)
    assert report.dropped == ("a",)
    assert store.get("b") is not None


def test_a_read_cache_misses_rather_than_serves_stale():
    cache = ReadCache()
    record = Record.put("k", "one", generation=1)
    cache.put(record)
    assert cache.get("k", current_generation=1) is not None
    assert cache.get("k", current_generation=2) is None
    assert cache.stats()["misses"] == 1


def test_explain_reports_the_winner_for_every_key():
    from atlas.config import build

    config = build(path="none.toml", env={"ATLAS_VNODES": "16"})
    rows = {key: (value, source) for key, value, source in explain(config)}
    assert rows["vnodes"][0] == 16
    assert rows["vnodes"][1] == "env:ATLAS_VNODES"
    assert rows["shards"][0] == 4
    assert rows["shards"][1] == "default"
