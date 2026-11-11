# Eksperymenty AK-Bench — opis pole po polu

Eksperyment to **wersjonowany plik YAML** w `configs/experiments/`. Nie jest komponentem instalowanym — **odwołuje się** do rejestrów (agentów, runtime'ów, wymiarów, evaluatorów, metryk, zadań). Planowanie (`validate`, `plan`) jest w pełni oddzielone od wykonania: nie dotyka workspace, agenta ani sieci, a odrzuca definicje nierunnable **przed** startem, z kodami błędów. Wykonanie (`experiment run`) rozwija plan w runy: `runs = tasks × variants × repetitions`.

---

## 1. Pola nagłówkowe (poziom pliku)

| Pole | Znaczenie |
|---|---|
| `schema_version: "1.0"` | wersja schematu deskryptora; walidator odrzuca nieznane pola (`extra="forbid"`) |
| `id` | stabilny identyfikator eksperymentu, np. `knowledge-replay-atlas` |
| `version` | wersja definicji; zmiana treści = nowa wersja |
| `title` / `description` | opis dla człowieka; `description` w shipped przykładach jest długa i argumentuje *dlaczego* eksperyment ma taką postać (co izoluje, czego nie mierzy) |

## 2. `experiment.type` — co eksperyment wariuje

| Typ | Wymagania | Zastosowanie |
|---|---|---|
| `configuration` | — | dowolna konfiguracja; domyślny |
| `agent_comparison` | macierz musi zawierać wymiar `agent` | porównanie agentów |
| `model_comparison` | macierz musi zawierać wymiar `model` | porównanie modeli pod jednym agentem |
| `knowledge_replay` | blok `knowledge` obowiązkowy | eksperyment uczący się (pamięć) |

Zasada strukturalna: typy konfiguracyjne i uczące się są **rozdzielone celowo** — zmieszanie efektu pamięci ze zmianą konfiguracji czyni je nierozróżnialnymi.

## 3. `agent` — agent pod testem

- **`id`** — id Agent Descriptora (`codex`). Walidacja: agent musi istnieć, adapter musi być zaimplementowany (`agent_unknown`).
- **`version`** — wersja deskryptora (opcjonalna).
- **`config`** — parametry agenta. Dla `codex` (z `configuration_schema` deskryptora):
  - `model` — model żądany (`-m/--model`); weryfikacja przez `turn_context.model` w rollout. **Pinowanie jest ważne**: bez niego agent użyje własnego defaultu, którego router może nie serwować.
  - `sandbox_mode` — `read-only` \| `workspace-write` (default) \| `danger-full-access` (`-s/--sandbox`).
  - `approval_policy` — `never` (default) \| `on-request` \| `on-failure`.
  - `reasoning_effort` — **nie-sterowalny** (`controllable: false`): walidator odrzuci eksperyment próbujący go wariować (`agent_parameter_uncontrollable`).
- **`required_capabilities`** (poziom `experiment`, nie `agent`) — lista capabilities, które agent musi mieć `verified`/`partial`, inaczej `capability_unavailable`.

## 4. `execution` — tryb i runtime

- **`mode`**: 
  - `direct` — agent działa bezpośrednio (np. codex CLI lokalnie); `runtime` **zabroniony** w tym trybie (walidator).
  - `runtime` — przez runtime bez routingu modeli.
  - `router` — przez LLM Router (modele, pluginy routingu/wiedzy).
- **`runtime.id`** — deskryptor runtime'u: `llm-router-ak-bench` (instancja własna) albo `llm-router-external` (współdzielona).
- **`runtime.lifecycle`**:
  - `managed` — AK-Bench **startuje i zatrzymuje** instancję na czas runa, z własnym środowiskiem. Tylko tu można przypiąć konfigurację pluginów per-run (`per_run_plugin_control: verified`). Healthcheck przed startem agenta, logi do artefaktów runa.
  - `external` — współdzielona instancja; AK-Bench tylko wysyła requesty. Konfiguracja pluginów per-run jest **odrzucana** (`per_run_plugin_control_unsupported`), bo nie da się jej przypiąć ani zweryfikować.
  - Deskryptor deklaruje `supported_lifecycles` — prośba o `managed` na instancji external jest odrzucana.

## 5. `dataset` — selekcja zadań

- **`id` / `version` / `path`** — wskazanie konkretnego datasetu (ścieżka względna wobec `datasets_dir`; nieistniejąca → `dataset_path_missing`).
- **`filters`** (AND między polami, OR wewnątrz listy):
  - `categories` — np. `[bug_fix, new_feature]`,
  - `difficulties` — np. `[hard, expert]`,
  - `task_ids` — id albo uid (`id@version`); pusta selekcja → `dataset_selection_empty` („eksperyment z zerem zadań nie produkuje dowodów").
- Planista sprawdza też timeouty zadań względem `execution_policy` (`_check_task_timeouts`).

## 6. `factors` — macierz wariantów

### 6.1. `dimensions` — lista `FactorReference`

Każdy element: **`id`** (id wymiaru) + opcjonalne **`values`** (zawężenie przestrzeni wartości wymiaru do podzbioru; pusta lista zabroniona). Wartości spoza zawężenia w baseline/kombinacjach są odrzucane (`baseline_value_invalid`).

Wymiary (`descriptors/dimensions/`):

| Wymiar | Typ | Sterowalny | Przestrzeń wartości |
|---|---|---|---|
| `agent` | agent_reference | tak | id Agent Descriptorów |
| `model` | model_reference | tak | zweryfikowany inwentarz routera (`auto_codex`, `qwen/Qwen3.8-27B`, …) |
| `knowledge_enabled` | plugin_configuration | tak | bool |
| `knowledge_read_enabled` / `knowledge_write_enabled` | plugin_configuration | tak | bool |
| `routing_heuristic_enabled` / `routing_semantic_enabled` | plugin_configuration | tak | bool |
| `routed_model` | model_reference | **nie** | obserwowany: co router faktycznie zaserwował |
| `repetition` | integer | **nie** | zarezerwowany — powtórzenia idą przez `execution_policy.repetitions` |

Wymiar nie-sterowalny może być **obserwowany, nigdy wariowany** — próba wariowania go to `factor_unusable`.

### 6.2. `strategy` — jak z wymiarów powstają warianty

| Strategia | Algorytm | Przykład: 2 wymiary × 2 wartości |
|---|---|---|
| `full_factorial` | iloczyn kartezjański wszystkich wartości | 4 warianty |
| `selected_factors` | iloczyn tylko `factors.selected`; reszta przypięta do baseline | 2 warianty (1 wymiar wariuje) |
| `one_factor_at_a_time` | baseline jako **pierwszy** wariant + każda pojedyncza zmiana wartości | 3 warianty (baseline + 2 zmiany) |
| `pairwise` | zachłanne pokrycie parami: każda para wartości występuje w jakimś wariancie | 4 warianty przy 2×2 (przy większych oszczędza) |
| `custom_matrix` | dokładnie `combinations`, w podanej kolejności | ile wpiszesz |

Wszystkie strategie są **deterministyczne** (ten sam input → te same warianty w tej samej kolejności). Pusta lista wymiarów → jeden wariant `{}` (przypadek sanity).

### 6.3. `baseline` — punkt odniesienia

Mapowanie wymiar → wartość. Używany przez `selected_factors` (przypinanie) i `one_factor_at_a_time` (wymagany dla **każdego** wymiaru, inaczej `baseline_missing`). Walidacja: klucze muszą być zadeklarowanymi wymiarami, wartości muszą należeć do macierzy (`baseline_not_in_matrix`). Wariant równy baseline'owi ma flagę `is_baseline` — raporty mierzą wszystko względem niego (`delta_success = success_variant − success_baseline`).

### 6.4. `combinations` + `runtime_env`

Tylko dla `custom_matrix` (wymagane niepuste; przy innych strategiach zabronione). Każda kombinacja to mapowanie wymiar → wartość, plus opcjonalny klucz zarezerwowany **`runtime_env`**: mapa zmiennych środowiskowych (tylko skalary!) dla **managed** runtime'u tego wariantu. Po co: pipeline pluginów routera (`LLM_ROUTER_UTILS_PLUGINS_PIPELINE`) czytany jest **przy starcie procesu** — ramię z pluginem wiedzy musi go nazwać w swojej kombinacji. Planista zdejmuje klucz z wartości czynników, haszuje go do tożsamości wariantu, orchestrator przekazuje adapterowi runtime'u (aplikowany jako ostatni — wygrywa z deskryptorem i shellem). `runtime_env` przeciw runtime'owi nie-startowanemu przez run → `runtime_environment_needs_managed`.

## 7. `execution_policy`

| Pole | Zakres | Znaczenie |
|---|---|---|
| `repetitions` | 1–1000 | ile razy każdy (task, wariant) — mnożnik liczby runów |
| `concurrency` | 1–64 | równoległość runów |
| `timeout_seconds` | >0 | wall-clock na run agenta |
| `evaluation_timeout_seconds` | >0 | wall-clock na ewaluację |
| `retry_infrastructure_errors` | 0–10 | retry **awarii infrastruktury** |
| `retry_agent_failures` | tylko 0 | walidator odrzuca `1`: retry mierzy retry, nie agenta |

## 8. `isolation`

| Pole | Znaczenie / ograniczenia |
|---|---|
| `workspace_per_run` | **obowiązkowe `true`** — walidator odrzuca `false` (dwa runy w jednym workspace zanieczyszczają się) |
| `fresh_agent_session` | nowa sesja agenta na run |
| `clean_agent_context` | czysty kontekst; wymaga `fresh_agent_session` |
| `cleanup_workspace` | usuń workspace po runie (domyślnie `false` — artefakty zostają do inspekcji) |

## 9. `evaluation`

- **`evaluators`** — lista id deskryptorów evaluatorów: `pytest_evaluator`, `command_evaluator`, `diff_evaluator`, `static_analysis_evaluator`. Niezdeklarowany → `evaluator_undeclared`, niezaimplementowany → `evaluator_not_implemented`.
- **`baseline`** — `base_state` (ewaluacja też na stanie bazowym zadania) albo `none`.

## 10. `metrics` — lista id metryk do zebrania

Katalog: 36 metryk w 5 grupach (quality / efficiency / knowledge / reliability / agent_runtime), każda z dostępnością `computed` / `derived` / `unavailable` + powodem. Niezdeklarowana → `metric_undeclared`; niepoliczalna → ostrzeżenie `metric_unavailable` (nie błąd — eksperyment rusza, metryka w raporcie będzie `null`/`unavailable`). Kluczowe: `task_success_rate`, `hidden_test_pass_rate`, `partial_success_rate`, `regression_rate`, `execution_time`, `input/output/total_tokens`, `tool_call_count`, `timeout_rate`, `agent_crash_rate`. Metryki wiedzy (`knowledge_write_count`, `hit_rate`, …) są dziś wszystkie `unavailable` — router nie eksportuje liczników per-plugin.

## 11. `limits` i `reporting`

- **`limits`**: `max_runs`, `max_variants`, `max_tasks` — sufit kosztu planu (`limit_runs` itd.). Planista liczy `tasks × variants × repetitions` i odrzuca przekroczenie **przed** startem.
- **`reporting`**: `generate_html` (domyślnie `false`), `generate_json` (`true`), `generate_csv` (`false`).

## 12. `knowledge` — blok eksperymentu pamięci (tylko `knowledge_replay`)

- **`plugin`** — id pluginu wiedzy (domyślnie `agentic_knowledge`).
- **`learning`** — ramię piszące:
  - `tasks` — lista `id@version` (min. 1), których praca produkuje wiedzę,
  - `write_enabled` / `read_enabled` — dostęp do wiedzy w ramieniu learningu (domyślnie oba `true`).
- **`replay`** — brama przed replayem:
  - `requires_readiness` (domyślnie `true`) — replay czeka na potwierdzoną gotowość bazy (zapisy asynchroniczne, indeksowanie w osobnym workerze),
  - `allow_unverified` (domyślnie `false`) — jawna zgoda na start bez potwierdzenia; run zapisywany jako `unverified`, nigdy `verified`. Statusy readiness: `ready` / `not_ready` / `unverified` / `unsupported` (na external routerze: `unsupported`, bo router odmawia odczytom `/knowledge`).
- **`fresh_control`** — **obowiązkowe `true`** (walidator odrzuca `false`): bez ramienia fresh efektu nie da się przypisać wiedzy.
- **`scenarios`** — min. 1, unikalne `id`; każde:
  - `id` — np. `same-task`, `fencing-twin`,
  - `type` — `exact_replay` (zadanie **musi** być w zbiorze learningu) | `related_transfer` (zadanie **nie może** być w zbiorze learningu) | `negative_transfer` (oczekiwane szkody wiedzy),
  - `task` — `id@version` zadania testowanego,
  - `note` — uzasadnienie relacji (w shipped przykładach bardzo rozbudowane: co dokładnie ma się przenieść i dlaczego).

Plan pamięci (`akbench knowledge plan`) buduje ramiona z **fingerprintami** faktów, które muszą być równe między replay a fresh (repo snapshot, wersja zadania, testy, evaluator, agent, parametry, limity) i odrzuca rozjazd z nazwą klucza. Izolacja przestrzeni nazw wiedzy: na managed instancji namespace jest własny per eksperyment; na external współdzielony (ostrzeżenie; dwa eksperymenty pamięci na jednej instancji zanieczyszczają się). Scope kolekcji = basename katalogu roboczego; runner przypina checkout ramion pamięci do `<run slug>/<nazwa repo>`, więc transfer pokrewny wymaga zadań na **wspólnym fixture**.

## 13. Co planista produkuje (`experiment plan --variants --json`)

- **PlanCounts**: `tasks`, `variants`, `repetitions`, `runs` — cztery liczby kosztu.
- **PlanEstimate**: górne ograniczenie czasu z deklarowanych timeoutów (fakt o konfiguracji, nie predykcja).
- **PlanTask**: uid, id, wersja, kategoria, trudność, digest, timeout.
- **PlanVariant**: stabilne `variant_id` (hash konfiguracji + parametrów agenta + środowiska), wartości czynników, `agent_config`, `environment_requests`, `config_hash`, `is_baseline`, `applies` (jak wartość została zaaplikowana), `runtime_environment`.
- **descriptor_snapshots** — digesty wszystkich deskryptorów, od których plan zależy (późniejsza edycja deskryptora nie reinterpretuje planu).
- **ValidationReport** — wszystkie ustalenia z kodami.

## 14. Workflow CLI

```bash
akbench experiment list
akbench experiment validate [FILE...]          # wszystkie kontrole planu 12.1
akbench experiment plan FILE --variants --json # koszt przed startem
akbench knowledge plan FILE                    # ramiona, fingerprinty, brama, izolacja
akbench knowledge readiness [--session X.json] # co deployment powie o bazie
akbench experiment run FILE --store [--only N] # --only = smoke test na N runach
akbench metrics run                            # agregacja metryk
akbench report all|experiment|task             # raporty HTML
akbench export experiment                      # JSON/CSV/HTML
akbench history                                # zapisana historia
akbench run single <task> --agent codex ...    # pojedynczy run poza eksperymentem
akbench evaluate task                          # ewaluacja workspace bez agenta
```

Walidacja odrzuca m.in.: pustą selekcję datasetu, nieznany agent/parametr, parametr nie-sterowalny, brak capability, nieznany runtime, tryb/lifecycle nieobsługiwane, plugin-factor bez runtime'u potrafiącego go przypiąć, wymiar nie-sterowalny jako czynnik, niezdeklarowany evaluator, limity przekroczone, baseline spoza macierzy, sprzeczności (`factor_config_conflict`, `comparison_without_factor`), `retry_agent_failures: 1`, `workspace_per_run: false`, transfer na zadanie learningu, `fresh_control: false`.

---

## Kompletny przykład z wyjaśnieniem każdego pola

Eksperyment „wiedza pomaga na tym samym zadaniu" na nowych zadaniach (learning pisze, replay czyta, fresh kontroluje):

```yaml
schema_version: "1.0"          # schemat deskryptora
id: knowledge-csvkit-replay    # stabilne id
version: "1.0.0"
title: Knowledge replay na csvkit
description: >-                # argumentacja: co izoluje, czego nie mierzy
  Czy wiedza zapisana przez learning na csvkit-quoted-field-001 pomaga
  w nowej sesji na tym samym zadaniu, względem ramienia bez wiedzy.

experiment:
  type: knowledge_replay       # typ uczący się; blok knowledge obowiązkowy

  agent:
    id: codex                  # Agent Descriptor
    version: "1.0.0"
    config:
      sandbox_mode: workspace-write  # -s workspace-write
      model: qwen/Qwen3.8-27B       # pin: bez tego default agenta

  execution:
    mode: router               # przez LLM Router (plugin wiedzy w routerze)
    runtime:
      id: llm-router-ak-bench  # instancja własna...
      lifecycle: managed       # ...startowana przez AK-Bench per run:
                               # własna przestrzeń wiedzy, readiness osiągalna

  dataset:
    filters:
      task_ids: [csvkit-quoted-field-001]  # selekcja: dokładnie to zadanie

  factors:
    strategy: full_factorial   # brak wymiarów -> 1 wariant {}
    dimensions: []
    baseline: {}

  execution_policy:
    repetitions: 1             # 1 learning + 2×1 scenariusz = 3 runy na wariant
    concurrency: 1
    timeout_seconds: 900       # limit na run agenta
    retry_infrastructure_errors: 1  # retry tylko awarii infra

  isolation:
    workspace_per_run: true    # obowiązkowe
    fresh_agent_session: true  # replay/fresh: nowa sesja bez historii
    clean_agent_context: true

  evaluation:
    evaluators: [pytest_evaluator]

  knowledge:
    plugin: agentic_knowledge
    learning:
      tasks: [csvkit-quoted-field-001@1.0.0]  # to zadanie pisze wiedzę
      write_enabled: true
      read_enabled: true
    replay:
      requires_readiness: true   # czekaj na settled indeksowanie
      allow_unverified: false    # bez potwierdzenia: blokada, nie zgadywanie
    fresh_control: true          # obowiązkowe ramię kontrolne
    scenarios:
      - id: same-task
        type: exact_replay       # to samo zadanie co learning
        task: csvkit-quoted-field-001@1.0.0
        note: nowa sesja, czysty workspace, tylko wiedza z learningu

  metrics: [task_success_rate, hidden_test_pass_rate, execution_time, total_tokens]
  limits: {max_runs: 16}       # sufit: 1 learning + 2×1 scenariusz = 3 runy
```

Plan: `akbench knowledge plan FILE` (ramiona + fingerprinty + brama), `akbench experiment validate FILE`, `akbench experiment plan FILE --variants`, potem `akbench experiment run FILE --store`.

Jeśli chcesz, mogę przygotować taki plik dla pełnej rodziny zadań (np. learning na jednym zadaniu z fixture'a + transfer na pozostałe — u nas każde fixture ma 1 zadanie, więc naturalny jest `exact_replay`; transfer wymagałby par na wspólnym fixture, jak atlas).