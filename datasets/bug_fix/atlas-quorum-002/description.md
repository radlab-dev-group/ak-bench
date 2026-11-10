# Restore the read side of the retiring-replica rule

Atlas is a sharded, replicated, fenced key-value store. Its repository suite
is green, and yet a cluster that is retiring two of a key's three replicas
keeps answering reads for that key, and a write to the same key goes through
its read phase as if nothing were wrong. Retiring one replica is routine;
retiring two of three at once is an operator error that the store is meant
to refuse loudly, with the quorum error that names the epoch.

The write side of the same rule is intact: the same cluster refuses a write
acknowledged by one healthy replica and one retiring one. Whatever is wrong
is wrong on one branch of one path.

`CONTRIBUTING.md` states where the truth lives: the decision records under
`docs/adr/` outrank `SPEC.md`, which outranks `README.md`, and the incident
notes are evidence, not rules. The decision record that states this rule is
written about the symptom, not the module.

Keep the public API, the wire format, the crash contract, and the repository
suite intact. Do not edit the specification, the decision records or the
incident corpus to match the code.
