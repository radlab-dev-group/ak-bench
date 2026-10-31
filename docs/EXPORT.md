# Export

`akbench export` writes one experiment out as a self-contained artifact: the
descriptor, the pinned descriptor snapshots, the variants, the runs, the
metrics, the manifests and the artifacts, plus the same document as JSON and
CSV.

Formats: `html` (default — the experiment page from the report, standalone),
`json` and `csv`.

```bash
akbench export --experiment exp-0001 [--format json|csv|html] [--output DIR] [--json]
```

## Filtering secrets

Before anything is written, every string in the export is screened for
material that must not leave the machine:

- environment variable names that the project classifies as secrets;
- JWTs and PEM blocks;
- OpenAI-style and AWS-style keys;
- `Authorization` headers and `Bearer` tokens;
- long hex strings that read as keys.

A match is not printed: the value is replaced by `[REDACTED:kind]` and the
kind is listed in the `redactions` section of the result, so a reader can see
that something was withheld without learning what it was. The screening
applies to JSON and CSV; the HTML export is the report, which already omits
secrets because the history stores them only as presence, never as value.

## What an export contains

- the experiment descriptor and its identity;
- the pinned descriptors with their digests;
- every variant with its configuration hash and baseline flag;
- every run with its verdict, score, failure class and error message;
- the recorded aggregates of the experiment;
- the artifacts with their checksums, and the manifest digest of each run;
- the redactions made, by kind and count.

The export is deterministic: the same history produces the same bytes, apart
from the `generated_at` timestamp, which is a field, not part of the payload
that is redacted or hashed.
