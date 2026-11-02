# A conversion answers with the oldest rate in force

`RateBook.rate_for` in `src/ledgerlite/fx.py` answers one question: which rate
of a currency was in force at a moment. The rule, as documented in the module:

- a rate is in force from the instant it was published until the next one is;
- the rate published **most recently at or before** the moment is the one in
  force;
- a rate published later is knowledge the ledger did not have, so it is never
  the answer, and there is no answer before the first publication.

When a currency's rate is revised, the old rate stops being the answer from the
revision onward. The defect makes the book answer with the first rate it can
find at or before the moment, so after a revision every conversion is silently
valued at the superseded rate — no error, just wrong numbers.

The repository's own suite is green on the pinned commit, because it publishes
a single rate per currency, for which "first in force" and "last in force" are
the same rate. The defect only shows up once a currency has more than one
published rate.
