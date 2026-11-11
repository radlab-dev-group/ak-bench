# AK-Bench — roadmapa rozwoju POZA planem 100%

> **Status:** propozycje rozwojowe *po* osiągnięciu 100% zgodności z
> `AK-Bench-implementation-plan.md` (plan: `AK-Bench-plan-do-100-procent.md`, fazy A, C–L;
> Faza B Docker — opcjonalna). Żadna faza z tej roadmapy **nie blokuje** 100%.
> Każda faza R1–R10 jest niezależnie wdrażalna i releasowalna.
>
> **Dla agenta kodującego:** pracuj fazami w kolejności R1 → R2 → R3 → R4 → R5 → R6
> (R7 może iść równolegle). R8–R10 dopiero po R1–R3. Po każdej fazie: testy,
> dokumentacja, CHANGELOG. Zasady z §0 planu 100% obowiązują bez zmian:
> brak fikcyjnych endpointów/ENV, `unavailable` zamiast zgadywania, sekrety poza logami,
> wsteczna kompatybilność YAML-i i schematu DB.

---

## 0. Mapa roadmapy

| Faza | Temat | Priorytet | Zależności | Szac. rozmiar |
|---|---|---|---|---|
| R1 | Statystyka i wiarygodność wyników | P1 — najpierw | — | duży |
| R2 | Budżet, koszt i guardraile | P1 — najpierw | R1 (szacowanie kosztu planu) | średni |
| R3 | Metryki routingu i retrieval | P1 — najpierw | G z planu 100% (metryki knowledge) | średni |
| R4 | Analiza porażek i trace mining | P2 | R1, R3 | średni |
| R5 | Ekosystem datasetów (import, jakość, trudność, kontaminacja) | P2 | — | duży |
| R6 | CI/CD, MLOps, OpenTelemetry | P2 | R2 (budżet w CI) | średni |
| R7 | Więcej agentów i pluginów | P2 (równolegle) | F z planu 100% (fake/http) | średni × N |
| R8 | LLM-as-judge + human evaluation | P3 | R1 (kalibracja), R4 | duży |
| R9 | Inteligentny scheduler (bandyci, cache, inkrementalność) | P3 | R1, R2, D z planu 100% | duży |
| R10 | Współdzielenie i leaderboard | P3 | I z planu 100% (export), R1 | średni |

**Zasada kolejności:** R1–R3 zamieniają AK-Bench z „narzędzia do odpalania runów”
w „narzędzie, którego wynikom można ufać w publikacji”. Dopiero potem skalowanie
(R4–R7) i automatyzacja (R8–R10).

**Czego roadmapa świadomie NIE zawiera** (odłożone z planu §27, nadal odłożone):
rozproszony scheduler/klaster workerów, konta użytkowników, wieloużytkownikowy SaaS.
Wszystko w R1–R10 działa lokalnie (CLI + statyczny HTML + opcjonalny `bench_ui`).

---

## FAZA R1 — Statystyka i wiarygodność wyników (P1)

### R1.1 Cel

Każde porównanie wariantów (np. Knowledge ON vs OFF) ma pokazywać nie tylko
średnią, ale: niepewność, istotność, wielkość efektu i ostrzeżenie, gdy danych
jest za mało. Bez tego wynik na 2–3 powtórzeniach to anegdota.

### R1.2 Stan obecny (punkt startu)

- `src/akbench/metrics/aggregate.py` — agregacje + `baseline_deltas`
  (`delta_success`, `speedup`, `token_saving`, obsługa baseline=0).
- `bench_ui/service.py` — Wilson CI i Pareto już istnieją w UI, ale **nie** w core
  (`metrics/`, `reporting/`). Trzeba je przenieść do core, żeby raport HTML
  i CLI widziały to samo.
- `reporting/data.py` + `render.py` — tabele wariantów bez kolumn niepewności.

### R1.3 Design

**Nowe moduły:**
- `src/akbench/metrics/statistics.py` — czyste funkcje (bez I/O, łatwe do testów):
  - `wilson_interval(successes, n, z=1.96)` → `(low, high)` dla proporcji.
  - `mean_ci(values)` → średnia + CI 95% (t-Student dla n≥2, inaczej `unavailable`).
  - `paired_bootstrap(a, b, n_resamples=10_000, seed)` → mediana różnicy + CI
    (parowanie po `task_uid`: ten sam task w obu wariantach).
  - `cohens_h(p1, p2)` — wielkość efektu dla proporcji; `cliffs_delta(a, b)` dla czasów/tokenów.
  - `holm_correction(p_values)` — korekta wielokrotnych porównań (Holm–Bonferroni).
  - `required_repetitions(p_baseline, delta, power=0.8, alpha=0.05)` — wzór na n
    dla proporcji (aproksymacja normalna); zwraca int + zastrzeżenie o założeniach.
- `src/akbench/metrics/comparison.py` — `compare_variants(runs_a, runs_b)`:
  wejście = listy runów z `HistoryStore`, wyjście = `ComparisonReport`
  (delta, CI, p-value, effect size, n, status: `ok | low_sample | insufficient_data`).
  - Parowanie obowiązkowe, gdy oba warianty mają te same `task_uid`; bez parowania
    → bootstrap nieparowany + flaga `unpaired`.
  - `n < 3` w którejkolwiek grupie → status `low_sample`, p-value = `unavailable`
    (nie liczymy testu na 2 punktach i nie udajemy, że jest).
  - Ostrzeżenie o „peekingu”: jeśli użytkownik patrzy na wyniki w trakcie runu
    i zatrzymuje eksperyment, gdy wygląda dobrze — dopisz do docs, że p-value
    są wtedy zawyżone (sequential testing). Nie implementuj alpha-spending w R1.

**Rozszerzenie modelu danych:**
- `ComparisonReport.as_dict()` z polami: `metric`, `baseline`, `variant`,
  `delta`, `ci_low`, `ci_high`, `p_value`, `effect_size`, `n_baseline`, `n_variant`,
  `paired`, `status`, `notes[]`.
- Nowa tabela? **Nie** — porównania liczone w locie z `task_runs` (jak dziś
  agregacje). Jeśli okaże się wolne, dodaj cache w `experiment_metrics` w R9.

**Integracja:**
- `metrics/aggregate.py` — `baseline_deltas()` dostaje opcjonalnie CI/p-value
  (nowe pola, stare zachowane).
- `reporting/render.py` — w raporcie eksperymentu: kolumny `delta ± CI`, `p`,
  `effect`, badge `low_sample` (żółty) / `insufficient_data` (szary).
  Tabela „Not verified” zostaje bez zmian.
- `bench_ui/service.py` — usuń lokalne liczenie Wilsona, importuj z core
  (jeden kod, dwa widoki).
- CLI: `akbench metrics compare --experiment <uid> --baseline <variant> --variant <variant>`
  (nowy podkomendant w `cli/metrics.py`) + `--json`.

**Testy:**
- Unit: Wilson (znane wartości: 8/10 → CI), bootstrap (seedowalny, deterministyczny),
  Cohen's h, Holm (3 p-value), `required_repetitions` (monotoniczność w delcie).
- Unit: `low_sample` dla n=2, `insufficient_data` dla n=0/1, parowanie po task_uid.
- Integration: syntetyczny eksperyment (fake agent, 2 warianty × 5 tasków) →
  `metrics compare` zwraca sensowną deltę; raport HTML zawiera kolumny CI.
- Reprodukcyjność: ten sam seed → ten sam wynik (test determinizmu).

**Kryterium akceptacji:** raport eksperymentu Knowledge ON/OFF pokazuje
`delta_success ± CI`, `p`, `effect` i badge przy małej próbie; `metrics compare`
działa z CLI; zero regresji w istniejących testach `test_metrics.py` / `test_reporting.py`.

**Pułapki:** nie licz p-value dla metryk `unavailable` (knowledge bez sygnałów);
nie mieszaj parowanych i nieparowanych w jednym teście; nie pokazuj p-value
bez n i bez CI (samo `p<0.05` to nie wynik).

---

## FAZA R2 — Budżet, koszt i guardraile (P1)

### R2.1 Cel

Eksperyment nie może spalić nieograniczonych pieniędzy/czasu. Planner szacuje
koszt *przed* runem, a runner zatrzymuje się, gdy limit pęknie.

### R2.2 Stan obecny

- `pricing.example.yaml` + `bench_ui/pricing.py` — ceny per model (tylko UI).
- `ExperimentBody.limits` — dziś tylko `max_runs`. Brak limitu kosztu/czasu/tokenów.
- Koszt agenta Codexa: `cost_usage: unsupported` (CLI nie raportuje kosztu) —
  koszt liczony z tokenów × cena modelu, nigdy z deklaracji agenta.

### R2.3 Design

**Model cen:**
- `src/akbench/metrics/pricing.py` — `PricingTable` z `pricing.yaml` (przenieś
  logikę z `bench_ui/pricing.py` do core; UI importuje z core).
  Format: `model_id → {input_per_1k, output_per_1k, currency}`.
  Brak ceny dla modelu → koszt `unavailable` (nie 0), z powodem w raporcie.
- `estimate_cost(run_record, pricing)` → `cost_usd | None` + `cost_source`
  (`tokens×price | unavailable`). Tokeny z `observations` (Codex rollout);
  brak tokenów → `unavailable`.

**Limity w eksperymencie** (`experiments/descriptor.py`, `Limits`):
```yaml
limits:
  max_runs: 24
  max_cost_usd: 50.0        # nowy
  max_wall_time_seconds: 7200  # nowy
  max_total_tokens: 1000000    # nowy (opcjonalny)
```
Walidacja: ujemne/zero → błąd; `max_cost_usd` bez cen dla modeli w macierzy →
warning `valid_with_warnings` (nie blokuje, ale raportuje).

**Szacowanie planu (planner):**
- `planner.py` — `PlanCounts` dostaje `estimated_cost_usd` (suma po wariantach:
  `repetitions × tasks × tokens_per_run_est × price`). Tokeny per run szacuj
  z historii (średnia z `task_runs` dla tego tasku/agenta), a gdy brak historii:
  `estimated_cost = unavailable` + dolne/górne ograniczenie z `max_total_tokens`.
  **Nigdy nie zgaduj ceny ani tokenów.**
- `experiment plan` wypisuje: `runs`, `estimated_cost`, `limits` — przed runem.

**Guardraile w runnerze** (`cli/experiments.py::_run_experiment`):
- Po każdym runie: suma `cost_usd` (tylko znane koszty) + wall time.
  Przekroczenie → przerwij pętlę, oznacz eksperyment `incomplete`
  (nie `valid`), dopisz do historii `budget_exceeded: {limit, actual}`.
- Koszty nieznane (`unavailable`) nie zatrzymują runu, ale są liczone
  i pokazane jako „≥ X (niekompletne)”.

**Raport:** dashboard + raport eksperymentu: koszt per wariant/task/model,
wykres koszt–jakość (Pareto z `bench_ui` przenieść do `reporting/render.py`
jako statyczny SVG — bez JS, zgodnie z §5 planu).

**Testy:** pricing (brak modelu → unavailable), planner (szacunek z historii
vs brak historii), guardrail (fake agent + `max_cost_usd: 0.01` → stop po N runach,
status `incomplete`), CLI `plan` wypisuje koszt.

**Kryterium akceptacji:** eksperyment z `max_cost_usd` zatrzymuje się po przekroczeniu
i jest oznaczony `incomplete`; `plan` pokazuje szacunek lub `unavailable` z powodem;
raport ma wykres koszt–jakość.

---

## FAZA R3 — Metryki routingu i retrieval (P1)

### R3.1 Cel

Odpowiedzieć na pytania badawcze, których dziś nie da się policzyć:
*czy router wybrał dobrze? czy retrieval trafił w relevantną wiedzę?
czy wstrzyknięta wiedza została użyta?*

### R3.2 Routing (po stronie routera, lifecycle `managed`)

**Nowe metryki** (`descriptors/metrics/routing.yaml`, grupa `routing`):
- `routing_regret` — dla każdego tasku: `success_oracle − success_chosen`,
  gdzie oracle = najlepszy model spośród testowanych w eksperymencie na tym tasku.
  Wymaga eksperymentu z ≥2 modelami na tych samych taskach; inaczej `unavailable`.
- `routing_accuracy` — odsetek requestów, gdzie wybrany model = oracle (per task).
- `escalation_rate` — odsetek requestów eskalowanych (z logu routera, jeśli jest).
- `model_distribution` — rozkład faktycznie użytych modeli per wariant
  (z `model_evidence` / `routed_model` — już zbierane w `lifecycle.RunContext`).

**Implementacja:** `src/akbench/metrics/routing.py` — agregacja z `model_observations`
+ `evaluations` (join po `task_uid`). Oracle liczony **tylko** z runów tego samego
eksperymentu (nie z historii globalnej — inaczej wyciek między eksperymentami).
Testy: syntetyczne runy 2 modeli × 3 taski → regret/accuracy zgodne z ręcznym wyliczeniem.

### R3.3 Retrieval quality (po Fazie G planu 100%)

**Ground truth:** opcjonalne pole `relevant_knowledge: [doc_id, …]` w `task.yaml`
(dodane w Fazie G3). Bez pola → metryki `unavailable` (nie 0).

**Nowe metryki** (`descriptors/metrics/knowledge.yaml`, dopisać):
- `retrieval_hit_at_k` (k=5 domyślnie) — czy relevantny doc jest w top-k.
- `retrieval_ndcg_at_k` — pozycja relevantnych w rankingu.
- `retrieval_mrr` — reciprocal rank pierwszego trafienia.
- `knowledge_utilization` — już z Fazy G3 (korelacja wstrzyknięcia z tool calls);
  w R3 dopnij ją do raportu jako osobną kolumnę obok retrieval (rozdzielenie §17).

**Implementacja:** `src/akbench/plugins/knowledge_metrics.py` (z Fazy G) dostaje
funkcje `hit_at_k(retrieved, relevant, k)`, `ndcg_at_k(...)`, `mrr(...)` — czyste,
testowalne na fixture-listach. Ranking z logu routera (`router.log`, managed);
bez logu → `unavailable`.

**Raport:** strona pluginu (`plugins/index.html`) + raport eksperymentu:
tabela retrieval (hit@k, nDCG, MRR, utilization) per wariant, z `source` i `n`.

**Kryterium akceptacji:** eksperyment knowledge-replay z `relevant_knowledge`
w taskach pokazuje hit@k/nDCG/utilization per wariant; bez ground truth —
`unavailable` z powodem; routing regret działa na eksperymencie 2-modelowym.

**Pułapki:** oracle z tego samego eksperymentu (nie globalny); retrieval ≠ utilization
(zawsze dwie kolumny); nDCG liczony na poziomie dokumentu, nie chunka, chyba że
task deklaruje chunki (pole `relevant_knowledge` z `chunk_id` — obsłuż oba formaty).

---

## FAZA R4 — Analiza porażek i trace mining (P2)

### R4.1 Cel

Zamiast czytać dziesiątki logów: automatyczne grupowanie porażek i eksport
trajektorii do dalszej analizy/treningu.

### R4.2 Failure clustering

**Nowe:** `src/akbench/analysis/failures.py`
- Wejście: runy z `verdict != passed` + `failure_class` + `evaluation.details`
  + statystyki tool calls + statystyki diffa.
- Algorytm deterministyczny (bez zależności ML w R4): reguły na
  (`verdict`, `failure_class`, kategoria testu, który test padł) → etykiety:
  `test_failure`, `timeout`, `infra`, `regression`, `evaluator_error`, `agent_crash`.
  Wewnątrz `test_failure`: grupowanie po nazwie padającego testu (prefiks modułu).
- Wyjście: `FailureCluster {label, count, share, example_run_uids[], tasks[]}`.
- Raport: sekcja „Failure analysis” w raporcie eksperymentu (tabela + przykłady).
- CLI: `akbench metrics failures --experiment <uid>`.

**Testy:** syntetyczne runy → klastry zgodne z oczekiwaniami; runy `passed`
nigdy w klastrach; `infra` oddzielone od `agent` (zasada §29.18).

### R4.3 Trace mining / eksport trajektorii

**Nowe:** `src/akbench/analysis/trajectories.py` + `akbench export trajectories`
- Eksport per run: `task + workspace diff + tool calls + final message + verdict`
  jako JSONL (format SFT: `messages[]`; format DPO: `chosen/rejected` z par
  baseline vs variant na tym samym tasku — tylko gdy oba runy istnieją).
- Redakcja jak w Fazie I (`--no-prompts` itd. dziedziczone). Anonimizacja:
  ścieżki absolutne → względne, sekrety → `[redacted]` (użyj `export/redact.py`).
- Manifest eksportu: skąd pochodzi (experiment/run uids), hash, data.

**Kryterium akceptacji:** `metrics failures` grupuje porażki; `export trajectories`
produkuje poprawny JSONL SFT/DPO z redakcją; raport ma sekcję Failure analysis.

---

## FAZA R5 — Ekosystem datasetów (P2)

### R5.1 Import zewnętrznych benchmarków

**Nowe:** `src/akbench/datasets/importers/` — pakiet z importerami:
- `swebench.py` — mapowanie formatu SWE-bench (repo, commit, problem statement,
  FAIL_TO_PASS / PASS_TO_PASS) na Task Descriptor AK-Bench. Hidden tests = FAIL_TO_PASS
  poza workspace (jak dziś). Importer zapisuje `source` + oryginalne ID w `task.yaml`.
- `generic.py` — importer generyczny JSONL (`id, repo, ref, description, tests`)
  dla dowolnego benchmarku o tej strukturze.
- CLI: `akbench dataset import --from swebench --output datasets/imported/ …`
  + `dataset validate` na zaimportowanym (mutacje: dla SWE-bench brak mutacji —
  task oznaczony `requires_mutation: false`, repo z prawdziwym commitem).

**Testy:** fixture SWE-bench (3 instancje) → import → validate → E2E na fake agent.
Licencja/źródło w `task.yaml` obowiązkowe (pole `source`).

### R5.2 Jakość i trudność zadań

**Nowe:** `src/akbench/datasets/quality.py`
- `quality_score(task)` — deterministyczny scoring: determinizm testów (2× ten sam
  wynik), siła hidden tests (czy mutacja jest wykrywana — już jest `MutationVerifier`),
  pokrycie (public vs hidden), czas wykonania, flakiness (powtórz 3×, ta sama odpowiedź).
- Kalibracja trudności (model Rascha, uproszczony): z historii runów
  `P(pass | agent, task)` → parametr trudności tasku + zdolności agenta.
  Implementacja: iteracyjne dopasowanie (bez `scipy` — czysty Python, n mały).
  Wynik: `difficulty_calibrated` obok deklarowanej `difficulty` w raporcie tasku.
- CLI: `akbench dataset quality [--task <uid>]`.

### R5.3 Kontaminacja

**Nowe:** `src/akbench/datasets/contamination.py`
- Canary: unikalny string w hidden tests (`AKBENCH_CANARY_<hash>`) — test, czy
  agent „zgadł” odpowiedź bez pracy (diff zawiera canary → flaga `possible_leak`).
- N-gram overlap: porównanie opisu zadania z public tests (wysoki overlap =
  zadanie zbyt łatwe do zgadnięcia) — heurystyka, oznaczana jako `unverified`.
- Raport tasku: sekcja „Contamination checks” z wynikami.

**Kryterium akceptacji:** import SWE-bench fixture działa E2E; `dataset quality`
zwraca scoring + kalibrację z historii; canary wykrywa wyciek w teście syntetycznym.

---

## FAZA R6 — CI/CD, MLOps, OpenTelemetry (P2)

### R6.1 Regression gate w CI

**Nowe:** `akbench experiment gate --experiment <uid> --baseline <variant> --min-delta <x>`
- Zwraca exit code 0/1 wg R1 (`delta_success` + CI): gate przechodzi, gdy
  dolna granica CI delty ≥ `--min-delta` (domyślnie 0). `low_sample` → exit 2
  (nie „pass”, nie „fail” — „nie wiemy”).
- Szablon `.github/workflows/akbench-gate.yml` w `docs/` (przykład, nie narzucany):
  fake agent + mały dataset, gate na PR.
- Testy: gate pass/fail/low_sample na syntetycznych danych.

### R6.2 Eksport do MLflow / W&B (opcjonalny)

**Nowe:** `src/akbench/export/mlflow.py`, `wandb.py` — cienkie adaptery:
metryki per wariant + parametry (snapshoty) + artefakty (raport HTML, manifest).
Zależności **opcjonalne** (`pip install akbench[mlflow]`), bez nich CLI zgłasza
`unsupported` z instrukcją instalacji. Nigdy nie wysyłaj sekretów (redakcja z Fazy I).

### R6.3 OpenTelemetry (opt-in)

**Nowe:** `src/akbench/observability/otel.py` — spany dla lifecycle runu
(`preparing → … → finalizing`), agenta, evaluatora, runtime. Włączane przez
`AKBENCH_OTEL=1` + `OTEL_EXPORTER_OTLP_ENDPOINT`. Bez env: zero narzutu, zero logów.
Mapowanie: `RunState` → span, `TransitionLog` → events. Test: in-memory exporter
w testach, asercja spanów dla jednego runu.

**Kryterium akceptacji:** gate działa w CI (exit codes 0/1/2); MLflow/W&B eksport
na stubie; OTel spany w teście in-memory; bez zależności opcjonalnych wszystko działa.

---

## FAZA R7 — Więcej agentów i pluginów (P2, równolegle)

### R7.1 Szablon dodawania agenta (checklist w docs)

Każdy nowy agent = spike → deskryptor → adapter → testy kontraktowe → docs.
Szablon w `docs/AGENT_ADAPTERS.md` (rozdział „Adding an agent” z checklistą §6.1 planu).

### R7.2 Konkretni kandydaci (w tej kolejności)

1. **Claude Code** (CLI, process) — analogiczny do Codexa; spike: flaga non-interactive,
   format zdarzeń, token usage, sandbox. Deskryptor z capabilities z dowodami.
2. **Aider** (CLI, process) — spike: tryb headless, format wyjścia, model config.
3. **OpenHands** (HTTP/service) — spike: API sesji, streaming, workspace binding.
   Jeśli API nie pozwala na izolację workspace — `workspace_binding: unsupported`
   i eksperymenty pamięciowe dla niego są blokowane przez planner (poprawnie).

Każdy: `src/akbench/agents/<name>.py` + `descriptors/agents/<name>.yaml` +
`tests/contract/test_<name>_adapter_contract.py` + rozdział w `AGENT_INTEGRATION.md`
(oddzielny plik per agent: `docs/AGENT_<NAME>_INTEGRATION.md`).

### R7.3 Pluginy

- Przykładowy drugi plugin knowledge/routing (np. wariant z innym mechanizmem
  retrieval) jako dowód, że plugin = deskryptor + adapter bez zmian w silniku.
- Plugin health: `akbench plugin verify` już istnieje — dodaj `--json` z powodami
  `unverified` (dlaczego, nie tylko status).

**Kryterium akceptacji:** co najmniej 1 nowy realny agent (Claude Code lub Aider)
przechodzi testy kontraktowe i E2E; `agent-comparison` działa z 3 agentami.

---

## FAZA R8 — LLM-as-judge + human evaluation (P3)

> ⚠️ Najwyższe ryzyko metodologiczne roadmapy. Judge bez kalibracji produkuje
> pozorne wyniki. R8 dopiero po R1 (statystyka) i z obowiązkową kalibracją.

### R8.1 Judge protocol

**Nowe:** `src/akbench/evaluators/judge.py` — evaluator `llm_judge`:
- Wejście: diff + final message + rubric (z `task.yaml`, pole `rubric: [...]`).
- Tryb pairwise (A vs B, ślepo, rotacja kolejności) preferowany nad punktowym.
- Judge = agent/model wskazany w deskryptorze evaluatora (nie hardkodowany).
- Wyjście: `verdict: partial/passed` + `score` + uzasadnienie (zachowane w `raw`).
- **Zakaz:** judge nie ocenia własnych runów bez flagi `self_evaluation: true`
  (raportowana w metrykach jako osobna grupa).

### R8.2 Kalibracja i bias

**Nowe:** `src/akbench/evaluators/judge_calibration.py`
- Zbiór kalibracyjny: ≥20 par z znanym verdictem (z hidden tests).
- Metryki: zgodność judge vs hidden tests (accuracy, Cohen's kappa),
  position bias (ta sama para w obu kolejnościach), verbosity bias
  (korelacja score z długością diffu).
- Judge bez kalibracji w raporcie: verdict oznaczony `unverified`.
- CLI: `akbench evaluate judge-calibration --evaluator llm_judge`.

### R8.3 Human evaluation

**Nowe:** w `bench_ui` — widok oceny: para diffów (A/B, ślepo), rubric checklist,
zapis ocen do `human_evaluations` (nowa tabela: `run_uid, evaluator, rubric_scores, notes`).
Metryki: inter-annotator agreement (Cohen's kappa dla 2, Krippendorff's alpha dla N).
Eksport ocen w `export` (Faza I) jako CSV.

**Testy:** judge na fixture (deterministyczny stub-judge), kalibracja na syntetyce,
kappa na znanych ocenach, ślepota (A/B bez etykiet w UI payloadzie).

**Kryterium akceptacji:** judge z kalibracją (kappa + bias raportowane);
human eval w UI z agreement; judge bez kalibracji = `unverified` w raporcie.

---

## FAZA R9 — Inteligentny scheduler (P3)

### R9.1 Alokacja powtórzeń (bandyci)

**Nowe:** `src/akbench/experiments/allocation.py`
- Zamiast stałych `repetitions` dla wszystkich: Thompson sampling na
  `P(pass)` per (variant, task) — kolejne powtórzenia trafiają tam, gdzie
  niepewność jest największa, do wyczerpania `max_runs` / `max_cost_usd` (R2).
- Tryb: `execution_policy.allocation: fixed | adaptive` (domyślnie `fixed` —
  wsteczna kompatybilność). Adaptive wymaga seedowalnego RNG (reprodukcyjność).
- Raport: ile powtórzeń dostał każdy wariant/task i dlaczego (log decyzji).

### R9.2 Cache i inkrementalność

- Klucz cache runu: `hash(task_digest + variant_config + agent_version + evaluator_version)`.
  Trafienie → pomiń run, oznacz `cached: true` (nie licz jako nowy run w metrykach,
  ale pokaż w raporcie).
- `experiment run --only-changed` — wykonaj tylko runy, których klucz nie jest w historii.
- Testy: drugi run z `--only-changed` = 0 nowych runów; zmiana tasku → tylko jego runy.

### R9.3 (Opcjonalnie) Równoległość między eksperymentami

Kolejka eksperymentów (`experiment queue`), priorytety, limit globalny.
Bez klastra — tylko lokalna kolejka w jednym procesie/pliku DB.

**Kryterium akceptacji:** tryb adaptive alokuje powtórzenia zgodnie z logiem decyzji;
`--only-changed` pomija niezmienione runy; tryb fixed = dzisiejsze zachowanie.

---

## FAZA R10 — Współdzielenie i leaderboard (P3)

### R10.1 Publiczny pakiet eksperymentu

Rozszerz `export` (Faza I): `akbench export public --experiment <uid>` —
samowystarczalny pakiet: deskryptor, snapshoty, warianty, runy, metryki,
manifesty, raport HTML, `README` z metodą i ograniczeniami. Redakcja pełna
(sekrety, prompty opcjonalnie, ścieżki absolutne). Walidacja pakietu:
`akbench export verify <pakiet>` (schemat + brak sekretów — skan wzorców kluczy).

### R10.2 Statyczny leaderboard

**Nowe:** `akbench report leaderboard --dataset <id>` — statyczna strona:
tabela agent×model×plugin z `delta ± CI` (z R1), filtrowanie po kategorii/trudności,
linki do raportów eksperymentów. Bez backendu, bez kont — czysty HTML jak dziś.
Generowanie z historii DB, deterministyczne (ten sam DB → ten sam HTML).

### R10.3 (Świadomie NIE) SaaS

Brak kont, brak bazy współdzielonej, brak API publicznego. Jeśli potrzeba
współdzielenia — pakiet z R10.1 + git. Decyzja udokumentowana w `docs/ARCHITECTURE.md`.

**Kryterium akceptacji:** `export public` + `verify` przechodzą; leaderboard HTML
generuje się z DB i zawiera CI z R1; brak sekretów w pakiecie (test skanera).

---

## 11. Checklist roadmapy (do odhaczania)

### P1
- [ ] R1 statystyka: Wilson/bootstrap/effect/Holm w core, `metrics compare`, CI w raporcie, badge `low_sample`
- [ ] R2 budżet: `PricingTable` w core, `max_cost_usd/max_wall_time`, szacunek w `plan`, guardrail → `incomplete`, wykres koszt–jakość
- [ ] R3 routing/retrieval: `routing_regret/accuracy`, `hit@k/nDCG/MRR`, utilization obok retrieval, oracle tylko z własnego eksperymentu

### P2
- [ ] R4 porażki: klastry + `metrics failures`; trajektorie SFT/DPO z redakcją
- [ ] R5 dataset: importer SWE-bench + generyczny, `dataset quality` + kalibracja trudności, canary/kontaminacja
- [ ] R6 CI/MLOps: `experiment gate` (0/1/2) + workflow, eksport MLflow/W&B (opcjonalny), OTel opt-in
- [ ] R7 agenci: ≥1 nowy realny adapter z testami kontraktowymi; `agent-comparison` z 3 agentami

### P3
- [ ] R8 judge: pairwise + kalibracja (kappa/bias) + human eval w UI z agreement; bez kalibracji = `unverified`
- [ ] R9 scheduler: alokacja adaptive (seedowalna), cache + `--only-changed`
- [ ] R10 sharing: `export public` + `verify`, statyczny leaderboard z CI

---

## Załącznik: co roadmapa zmienia w planie 100%

Roadmapa nie zmienia definicji 100% ani kolejności faz A–L (+ opcjonalna B).
Fazy R1–R10 dopisują się *po* L jako osobny strumień. Jeśli któraś faza R
wymaga zmiany schematu DB, deskryptora lub CLI — zrób to migracją/dokumentacją
w tej fazie, bez łamania YAML-i z planu 100% (test strażnika shipped YAML-i
z Fazy H musi dalej przechodzić).
