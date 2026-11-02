# ledgerlite

A double-entry bookkeeping engine: accounts, postings, the immutable journal,
foreign-currency conversion against a rate book, and a period close that posts
the balancing entries. Money is stored as exact integers of the account's
base unit, so the difficulty is in the rules, not the arithmetic.

The reconciliation module is declared and specified to the entry, but its body
raises `NotImplementedError`; that is the shape of the feature task built on
this fixture. The rest of the suite is narrow on purpose, so a defect can hide
behind it. Run the suite with `pytest`.
