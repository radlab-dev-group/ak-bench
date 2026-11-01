# notesapi

A Flask note-taking service: a note store with tags, a search function and a
synchronisation merge. The search and merge modules are declared and tested by
their specifications, but their bodies raise `NotImplementedError`; that is the
shape of the benchmark tasks built on this fixture.

Money is not involved; the difficulty is in the rules. Run the suite with
`pytest`.
