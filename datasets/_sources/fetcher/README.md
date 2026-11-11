# fetcher

A tiny HTTP fetcher over an injected transport (no network): `fetch`
follows redirects. It is a benchmark fixture for AK-Bench. The test
suite is narrow on purpose: it only fetches public hosts, so a
redirect-to-internal defect is invisible there.

Run the suite with `pytest`.
