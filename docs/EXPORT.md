# Export

`akbench export` writes one experiment out as a self-contained artifact: the
descriptor, the pinned descriptor snapshots, the variants, the runs, the
metrics, the manifests and the artifacts, plus the same document as JSON and
CSV.

Formats: `html` (default — the experiment page from the report, standalone),
`json` and `csv`.

```bash
akbench export experiment exp-0001 [--format json|csv|html] [--output DIR]
    [--no-prompts] [--no-diffs] [--no-traces] [--include-artifacts] [--json]
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

## Narrowing what leaves the machine

Secrets are always screened, but sometimes the publisher wants less than the
truth. Three switches narrow the export on purpose; with none of them the
export is what it was before:

```bash
akbench export experiment exp-0001 [--no-prompts] [--no-diffs] [--no-traces]
```

- `--no-prompts` — leaves out the agent's own text: its final message, the
  `last_message.txt` artifact and the prompt fields inside records (replaced
  by `[withheld]`, so the shape of the record survives). Verdicts, scores and
  metrics are the result and stay.
- `--no-diffs` — leaves out the change the agent produced: `diff.patch` and
  its siblings, `solution.zip`, and the diff fields inside records. The score
  the change earned stays.
- `--no-traces` — leaves out the step-by-step record: `agent_trace.jsonl`,
  `tool_calls.jsonl`, their packaged form `agent_traces.zip` and the
  stdout/stderr logs. The metrics the traces support stay.

A reduced export says what it left out: the `filters` section names the
closed switches and the `withheld` section counts the material by kind, so a
reader of the reduced document knows it is looking at a subset. The same
switches apply to `--include-artifacts`: a file filtered out of the document
does not travel out as a copy, and a JSON record that survives is stripped of
the fields the switches name.

## What an export contains

- the experiment descriptor and its identity;
- the pinned descriptors with their digests;
- every variant with its configuration hash and baseline flag;
- every run with its verdict, score, failure class and error message;
- the recorded aggregates of the experiment;
- the artifacts with their checksums, and the manifest digest of each run;
- the redactions made, by kind and count;
- when a switch was closed: the `filters` and the `withheld` counts.

`--include-artifacts` copies what each run produced under
`artifacts/<run uid>/` in the export directory, the filters above deciding
what may be copied.

The export is deterministic: the same history produces the same bytes, apart
from the `generated_at` timestamp, which is a field, not part of the payload
that is redacted or hashed.
