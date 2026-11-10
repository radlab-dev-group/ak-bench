# ADR-0004: A digest covers identity, not content

Status: accepted. Referenced by SPEC.md §6.5.

## Context

Anti-entropy compares replicas by range digests so that a key nobody reads
still converges. The first implementation hashed the value too, and a
cluster with a large blob under one key spent its convergence budget
re-hashing that blob on every pass. The second implementation hashed the
key, the generation and the LSN, and an operator then assumed that equal
digests meant equal bytes.

## Symptom

Two replicas report equal digests for a range and a client reads two
different values for a key in it. Nobody can say when the divergence began,
because the pass that was supposed to notice reported "clean" throughout.

## Decision

A digest covers the key, the generation and the LSN of every record in the
range. It does **not** cover the value. Two replicas with equal digests agree
on which version of each key they hold, and the store says so in the name of
the comparison function rather than pretending otherwise. Content equality is
a different property, guaranteed by the write path (one version, one value)
and by repair never merging, not by the digest.

A version is compared as a value: the vector is a set of (writer, counter)
pairs, and two vectors with the same pairs are the same vector whichever
order the writers were seen in. A digest, a repair decision and a convergence
check that treat the same version as two versions are wrong in the same way,
and the way is in how the version is represented, not in who was compared.

## Consequences

* A divergence is reported as the smallest key range whose digests differ,
  with the keys that differ by version, never as a count.
* Two replicas that differ in value but not in version are not a divergence
  to anti-entropy; they are a bug in whatever wrote the value, and the tool
  for that is `tools/parity.py`.
* Writers that arrive at two replicas in opposite orders produce the same
  vector; a pass over such replicas repairs nothing and reports clean.
