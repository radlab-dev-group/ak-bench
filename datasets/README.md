## All tasks in **AK-Benchmark**

| ID         | Task                           | Type            | Description                                                     | Difficulty | Created by                            | When added           |
| ---------- | ------------------------------ | --------------- | --------------------------------------------------------------- | ---------- | ------------------------------------- | -------------------- |
| `BF_001`   | `bookshop-stock-002`           | `bug_fix`       | [READ](./bug_fix/bookshop-stock-002/description.md)             | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `BF_002`   | `bookshop-tiers-001`           | `bug_fix`       | [READ](./bug_fix/bookshop-tiers-001/description.md)             | `hard`     | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `BF_003`   | `cadence-takeover-001`         | `bug_fix`       | [READ](./bug_fix/cadence-takeover-001/description.md)           | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `BF_004`   | `ledgerlite-rates-001`         | `bug_fix`       | [READ](./bug_fix/ledgerlite-rates-001/description.md)           | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `BF_005`   | `stockpile-writeoff-001`       | `bug_fix`       | [READ](./bug_fix/stockpile-writeoff-001/description.md)         | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `BF_006`   | `wordcount-001`                | `bug_fix`       | [READ](./bug_fix/wordcount-001/description.md)                  | `easy`     | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `BF_007`   | `walqueue-recovery-001`        | `bug_fix`       | [READ](./bug_fix/walqueue-recovery-001/description.md)          | `expert`   | Codex with `GPT 6.1 Sol`              | `2026-11-02 14:00`   |
| `BF_008`   | `depweaver-backtracking-001`   | `bug_fix`       | [READ](./bug_fix/depweaver-backtracking-001/description.md)     | `expert`   | Codex with `GPT 6.1 Sol`              | `2026-11-02 14:00`   |
| `NF_001`   | `cadence-catchup-001`          | `new_feature`   | [READ](./new_feature/cadence-catchup-001/description.md)        | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `NF_002`   | `freight-shop-001`             | `new_feature`   | [READ](./new_feature/freight-shop-001/description.md)           | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `NF_003`   | `ledgerlite-reconcile-001`     | `new_feature`   | [READ](./new_feature/ledgerlite-reconcile-001/description.md)   | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `NF_004`   | `notes-search-001`             | `new_feature`   | [READ](./new_feature/notes-search-001/description.md)           | `hard`     | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `NF_005`   | `notes-sync-001`               | `new_feature`   | [READ](./new_feature/notes-sync-001/description.md)             | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `NF_006`   | `slugify-001`                  | `new_feature`   | [READ](./new_feature/slugify-001/description.md)                | `easy`     | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `NF_007`   | `stockpile-fefo-001`           | `new_feature`   | [READ](./new_feature/stockpile-fefo-001/description.md)         | `expert`   | Local `qwen-38-Flash`/`qwen-38-27B`   | `2026-11-01 19:00`   |
| `NF_008`   | `streamforge-windows-001`      | `new_feature`   | [READ](./new_feature/streamforge-windows-001/description.md)    | `expert`   | Codex with `GPT 6.1 Sol`              | `2026-11-02 14:00`   |
| `NF_009`   | `typeweave-inference-001`      | `new_feature`   | [READ](./new_feature/typeweave-inference-001/description.md)    | `expert`   | Codex with `GPT 6.1 Sol`              | `2026-11-02 14:00`   |

`Difficulty` is the task descriptor's own `task.difficulty`
(`src/akbench/datasets/task.py`: `easy` | `medium` | `hard` | `expert`), so the
table and `akbench dataset list` can never disagree. Difficulty is a property of
the task, not of the timeout beside it: an `expert` task is one whose complete
solution a strong model does not reach in one pass, whatever the clock allows.
`expert` tasks are the ones an experiment plans when it wants to separate agents
that can hold a large invariant in mind from agents that can only patch locally.
The `task_ids` lists below are a convenience for the experiment YAML; they do
not repeat the difficulty, which the table above and the descriptors are the
source of.

Below is the list of the all available tasks without a split to task type

Single line
```yaml
task_ids: [ bookshop-stock-002, bookshop-tiers-001, cadence-takeover-001, ledgerlite-rates-001, stockpile-writeoff-001, wordcount-001, walqueue-recovery-001, depweaver-backtracking-001, cadence-catchup-001, freight-shop-001, ledgerlite-reconcile-001, notes-search-001, notes-sync-001, slugify-001, stockpile-fefo-001, streamforge-windows-001, typeweave-inference-001 ]
```

Multiline
```yaml
task_ids:
  - bookshop-stock-002
  - bookshop-tiers-001
  - cadence-takeover-001
  - ledgerlite-rates-001
  - stockpile-writeoff-001
  - wordcount-001
  - walqueue-recovery-001
  - depweaver-backtracking-001
  - cadence-catchup-001
  - freight-shop-001
  - ledgerlite-reconcile-001
  - notes-search-001
  - notes-sync-001
  - slugify-001
  - stockpile-fefo-001
  - streamforge-windows-001
  - typeweave-inference-001
```

### Bugfix tasks

---

**All `bugfix` tasks created by the local qwen models**

Single line
```yaml
task_ids: [ bookshop-stock-002, bookshop-tiers-001, cadence-takeover-001, ledgerlite-rates-001, stockpile-writeoff-001, wordcount-001 ]
```

Multiline
```yaml
task_ids:
  - bookshop-stock-002
  - bookshop-tiers-001
  - cadence-takeover-001
  - ledgerlite-rates-001
  - stockpile-writeoff-001
  - wordcount-001
```

**All `bugfix` tasks created by claude GPT 6.1 Sol model**

Single line
```yaml
task_ids: [ walqueue-recovery-001, depweaver-backtracking-001 ]
```

Multiline
```yaml
task_ids:
  - walqueue-recovery-001
  - depweaver-backtracking-001
```

**list of all `bugfix` tasks**

Single line
```yaml
task_ids: [ bookshop-stock-002, bookshop-tiers-001, cadence-takeover-001, ledgerlite-rates-001, stockpile-writeoff-001, wordcount-001, walqueue-recovery-001, depweaver-backtracking-001 ]
```

Multiline
```yaml
task_ids:
  - bookshop-stock-002
  - bookshop-tiers-001
  - cadence-takeover-001
  - ledgerlite-rates-001
  - stockpile-writeoff-001
  - wordcount-001
  - walqueue-recovery-001
  - depweaver-backtracking-001
```

---

### New feaure tasks

**All `new_feature` tasks created by the local qwen models**

Single line
```yaml
task_ids: [ cadence-catchup-001, freight-shop-001, ledgerlite-reconcile-001, notes-search-001, notes-sync-001, slugify-001, stockpile-fefo-001 ]
```

Multiline
```yaml
task_ids:
  - cadence-catchup-001
  - freight-shop-001
  - ledgerlite-reconcile-001
  - notes-search-001
  - notes-sync-001
  - slugify-001
  - stockpile-fefo-001
```

**All `new_feature` tasks created by claude GPT 6.1 Sol model**

Single line
```yaml
task_ids: [ streamforge-windows-001, typeweave-inference-001 ]
```

Multiline
```yaml
task_ids:
  - streamforge-windows-001
  - typeweave-inference-001
```

**list of all `new_feature` tasks**

Single line
```yaml
task_ids: [ cadence-catchup-001, freight-shop-001, ledgerlite-reconcile-001, notes-search-001, notes-sync-001, slugify-001, stockpile-fefo-001, streamforge-windows-001, typeweave-inference-001 ]
```

Multiline
```yaml
task_ids:
  - cadence-catchup-001
  - freight-shop-001
  - ledgerlite-reconcile-001
  - notes-search-001
  - notes-sync-001
  - slugify-001
  - stockpile-fefo-001
  - streamforge-windows-001
  - typeweave-inference-001
```

---
