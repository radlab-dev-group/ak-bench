"""The write and read paths, the fencing checks, and the public API."""

import pytest

from atlas.errors import KeyNotFoundError, QuorumError, StaleGenerationError
from atlas.values import Record


def test_put_then_get(store):
    result = store.put("user:1", {"name": "ada"})
    assert isinstance(result.record, Record)
    assert result.record.generation == 1
    assert store.get("user:1").value == {"name": "ada"}


def test_every_replica_named_by_the_plan_holds_the_write(store):
    result = store.put("user:2", {"n": 1})
    assert set(result.replicas) == set(store.replicas_for("user:2"))
    for replica in store.read_replicas("user:2"):
        assert replica.value == {"n": 1}


def test_a_second_write_advances_the_generation_by_one(store):
    first = store.put("k", 1).record
    second = store.put("k", 2, expected_generation=first.generation).record
    assert second.generation == first.generation + 1
    assert second.vector.get(second.writer) == 2


def test_an_offered_generation_that_is_not_current_is_refused(store):
    first = store.put("k", 1).record
    store.put("k", 2, expected_generation=first.generation)
    with pytest.raises(StaleGenerationError) as caught:
        store.put("k", 3, expected_generation=first.generation)
    assert caught.value.offered == first.generation
    assert caught.value.current == first.generation + 1


def test_delete_leaves_a_tombstone_that_a_read_does_not_see(store):
    store.put("k", 1)
    result = store.delete("k")
    assert result.record.deleted is True
    assert store.get("k") is None
    assert store.resolve("k").deleted is True


def test_deleting_an_absent_key_is_a_known_error(store):
    with pytest.raises(KeyNotFoundError):
        store.delete("never-written")


def test_a_deleted_key_can_be_written_again(store):
    store.put("k", 1)
    store.delete("k")
    result = store.put("k", 2)
    assert store.get("k").value == 2
    assert result.record.deleted is False


def test_the_shard_of_a_key_depends_on_the_key_and_the_shard_count_only(store):
    assert store.shard_of("user:9") == store.shard_of("user:9")
    assert 0 <= store.shard_of("anything") < int(store.config["shards"])


def test_quorum_arithmetic_is_reported(store):
    sizes = store.replicator.quorum_sizes()
    assert sizes["read_consistency"] + sizes["write_consistency"] > sizes["replication_factor"]


def test_a_read_needs_answers_not_values(store):
    # A key nobody has written is an answer, so the read must succeed.
    assert store.get("missing") is None


def test_stats_describe_the_cluster(store):
    stats = store.stats()
    assert stats["nodes"] == sorted(store.nodes)
    assert stats["shards"] == int(store.config["shards"])
    assert stats["epoch"] == store.placement.epoch()


def test_attributes_survive_a_round_trip(store):
    store.put("k", 1, attributes={"team": "storage", "tier": "hot"})
    record = store.get("k")
    assert record.attribute_map == {"team": "hot" if False else "storage", "tier": "hot"}


def test_a_write_with_an_impossible_quorum_fails_loudly(tmp_path, config):
    from atlas.config import ConfigError
    from atlas.store import AtlasBuilder

    with pytest.raises(ConfigError):
        AtlasBuilder().config(
            config.replaced(read_consistency=1, write_consistency=1, replication_factor=3)
        ).root(tmp_path / "bad").build()


def test_transaction_commits_when_nothing_moved(store):
    current = store.put("k", 1).record
    transaction = store.transaction("worker-a")
    transaction.read("k", current.generation)
    transaction.write("k", 2)
    assert store.commit_transaction(transaction) == [("k", 2)]
    assert store.get("k").value == 2


def test_transaction_aborts_when_a_read_key_moved(store):
    current = store.put("k", 1).record
    transaction = store.transaction("worker-a")
    transaction.read("k", current.generation)
    store.put("k", "someone else")
    with pytest.raises(StaleGenerationError):
        store.commit_transaction(transaction)
    assert store.get("k").value == "someone else"


def test_an_aborted_transaction_releases_its_leases(store):
    current = store.put("k", 1).record
    transaction = store.transaction("worker-a")
    transaction.read("k", current.generation)
    transaction.abort()
    assert transaction.state == "aborted"
    assert store.fence.lease("k") is None


def test_re_reading_a_key_at_a_new_generation_is_an_error(store):
    first = store.put("k", 1).record
    transaction = store.transaction("worker-a")
    transaction.read("k", first.generation)
    with pytest.raises(StaleGenerationError):
        transaction.read("k", first.generation + 1)
