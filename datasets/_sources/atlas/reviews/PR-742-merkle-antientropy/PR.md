# PR-742: Merkle buckets for the pre-rebalance anti-entropy pass

Closes PLAT-208. The pre-rebalance pass compares whole shard digests today, so
the first disagreement costs a full key exchange between the two replicas. This
adds a bucketed Merkle view so the pass can name the keys that differ without
exchanging values.

## What is in here

* `src/atlas/merkle.py` — `MerkleTree.build(store)` walks the store's live
  records in sorted key order, buckets them `leaf_size` at a time and digests
  each bucket over the (key, generation, lsn) triples. `Bucket.overlaps` and
  `Bucket.high` name the upper edge of a bucket, and buckets are compared by
  their lower edge, which is unique.
* `MerkleTree.differing(other)` — the keys two trees disagree about. When two
  replicas hold the same key with different generations the newer one wins; the
  pass is meant to be run twice in a row and settle the same way both times, so
  a tie is broken by the order the two trees are scanned.
* `antientropy.merkle_view(store)` — the entry point the operator runbook calls.

## Why the walk does not take a lock

The shard keeps accepting writes during a pass and the pass can take seconds.
Taking the key order once and reading each record when its bucket is closed
keeps the walk off the write path entirely; the alternative — copying the shard
into a snapshot — is the memory spike we are trying not to have during a
rebalance.

## Test plan

* `python -m pytest tests/`
* `python tools/check_arch.py`
* a manual pass against a two-replica shard with 10k keys
