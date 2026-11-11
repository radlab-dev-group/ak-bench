# AK-Bench — plan realizacji do 100% zgodności z `AK-Bench-implementation-plan.md`

> **Dokument dla agenta kodującego.** Wejście: audyt z 2026-11-10 (`AK-Bench-audyt-planu.md`,
> repo @ `125535b`, v0.1.1) + plan źródłowy `.plans/_partialy_done_to_verify/AK-Bench-implementation-plan.md` (§1–30).
> Cel: zamknąć **wszystkie** braki i odstępstwa wykryte w audycie, tak aby każdy punkt
> §1–30, MVP §27 i rezultat końcowy §30 był spełniony i udowodniony testami.
> Po zakończeniu każdej fazy: testy + dokumentacja + CHANGELOG. Nie wolno zostawiać stubów.
> **Faza B (Docker) jest OPCJONALNA i ostatnia** — patrz §0 i nagłówek Fazy B. 100% osiągasz bez niej.

---

## 0. Zasady obowiązujące dla każdej fazy (z §29 planu — nie negocjowalne)

1. Najpierw przeczytaj plan źródłowy (§1–30) i audyt. Nie zgaduj endpointów, flag CLI,
   nazw ENV ani formatów logów — każdą integrację potwierdź w kodzie/dokumentacji
   komponentu, w przeciwnym razie oznacz `unsupported` / `unverified`.
2. Nie umieszczaj logiki konkretnego agenta poza jego adapterem. Dodanie agenta =
   deskryptor + adapter + testy kontraktowe, **zero** zmian w orchestratorze,
   plannerze, evaluatorze.
3. Obserwuj tylko ENV jawnie wskazane w deskryptorach (allowlist). Sekretów nie zapisuj
   (co najwyżej `is_set`).
4. Zapisuj `requested` / `effective` / `observed` osobno. Konfiguracji nie uznawaj
   za aktywną bez weryfikacji.
5. Błędów infrastruktury nie licz jako błędów agenta. Nieudanych runów nie ukrywaj
   w raportach. Brak danych = `null` / `unavailable`, nigdy 0 i nigdy zgadywanie.
6. Każdy run: manifest + hashe + snapshoty deskryptorów. Każdy deskryptor: wersjonowany
   (`schema_version`, `id`, `version`), walidowany Pydantic, digest-pinowany.
7. Po każdej fazie: `AKBENCH_DB_BACKEND=sqlite .venv/bin/python -m pytest tests/unit tests/contract
   tests/integration tests/e2e -q` musi być zielony (poza testami oznaczonymi `live`/`postgres`,
   które mają się **skipować**, nie failować, bez swoich zależności).
8. Aktualizuj `CHANGELOG.md` (sekcja Unreleased) i dokumentację dotkniętego obszaru
   w tej samej fazie. Dokumentacja opisuje tylko to, co istnieje.
9. Zachowaj wsteczną kompatybilność: istniejące YAML-e eksperymentów, deskryptory
   i schemat DB (migracje Alembic) muszą dalej działać. Zmiana schematu = nowa migracja.
10. Nie refaktoruj bez potrzeby: przemianowania modułów z §5.1 (np. `categories/`,
    `sandbox/`) rozwiązuj dokumentacją mapowania (Faza K), nie przenosinami plików.

**Definicja „100%”:** wszystkie **obowiązkowe** punkty checklisty w §13 *tego dokumentu*
(„Checklist końcowa”; §13 planu źródłowego to Router Manager — to nie ta sama liczba)
(Faza B jest opcjonalna i nie wchodzi w definicję 100%), testy zielone na świeżym
klonie (bez sibling repo `ak-bench-data`, bez PostgreSQL, bez kluczy API),
wszystkie shipped YAML-e przechodzą `experiment validate` + `plan`.

**Kolejność faz:** A → C → D → E → F → G → H → I → J → K → L → **B (OPCJONALNA, ostatnia)**.
Fazy C–K są w większości niezależne i mogą iść równolegle, ale A jest warunkiem
wszystkich (zielony CI), a L weryfikuje 100% **bez** Fazy B. Faza B jest dodatkiem
po L — wdrażaj ją tylko, gdy zajdzie potrzeba (patrz banner Fazy B); jej pominięcie
nie blokuje release ani oznaczenia „100%”.

---

## FAZA A — Naprawa defektów świeżego klona (P0, blokuje wszystko)

Audyt: 18 błędów testów na świeżym klonie. Żadna kolejna faza nie ma sensu bez zielonego CI.

### A1. `.gitignore` zjada `mutations/parts/*.patch` (13 błędów) — ✅ NAPRAWIONE w `6102769`, został strażnik

**Objaw:** `can't open patch 'datasets/bug_fix/{atlas-drift-001,depweaver-backtracking-001}/mutations/parts/*.patch'`.
`parts.json` referencjonuje pliki, których nie ma w git, bo `.gitignore:19` zawiera
generyczny wpis `parts/` (szablon Pythona).

**Zadania:**
1. W `.gitignore` zamień `parts/` na `/parts/` (tylko root projektu) **albo** dodaj
   wyjątek `!datasets/**/mutations/parts/` + `!datasets/**/mutations/parts/*.patch`.
   Wybierz wariant minimalny i dopisz komentarz, dlaczego wyjątek istnieje.
2. Wygeneruj brakujące pliki `parts/*.patch` dla `atlas-drift-001` (5 części) i
   `depweaver-backtracking-001` (8 części) — są to podziały `mutation-001.patch`
   wg `parts.json` (kolejność + `witness`). Jeśli generator istnieje w repo
   (szukaj w `scripts/` i testach `test_atlas_family_tasks.py`,
   `test_senior_dataset_tasks.py`), użyj go; w przeciwnym razie napisz jednorazowy
   skrypt podziału i **zcommituj wynik** (pliki muszą być w git, nie generowane w locie).
3. Dodaj test strażnika: `tests/unit/test_dataset_integrity.py` (nowy) — dla każdego
   zadania z `parts.json` asercja, że każdy `patch` istnieje na dysku i jest
   śledzony przez git (`git ls-files --error-unmatch` w trybie CI, skip poza repo).
   Test ma wyłapać regresję „plik referencjonowany, ale niecommitowany”.

**Kryterium akceptacji:** `test_atlas_family_tasks.py` (5) i
`test_senior_dataset_tasks.py` (8) zielone na świeżym klonie; nowy test strażnika zielony.

### A2. Dangling symlink `data -> ../ak-bench-data` (3 błędy)

**Objaw:** `FileExistsError: '.../ak-bench/data'` w `RepositoryManager._ensure_seed`
(`mkdir(parents=True, exist_ok=True)` na dangling symlink). Sibling repo nie jest
częścią klona, więc świeży klon jest zepsuty.

**Zadania:**
1. Usuń symlink `data` z git (`git rm data`). Zastąp prawdziwym katalogiem
   `data/` z `.gitkeep` (i `.gitignore` już ma `/data/` — zostaw).
2. W `src/akbench/core/paths.py` i `config/models.py` upewnij się, że ścieżki
   `data/*` (artifacts, workspaces, runtime_instances, repos cache) są tworzone
   leniwie przez `bootstrap.initialize()` / `doctor`, a nie zakładane jako istniejące.
   `mkdir` musi obsługiwać istniejący katalog i istniejący plik (osobne błędy).
3. Zaktualizuj `README.md` (sekcja Quick start) i `docs/DEVELOPMENT.md`: `data/`
   jest lokalne, niecommitowane, usuwalne; historyczne dane w `ak-bench-data`
   importuje się przez `akbench migrate sqlite …` (już istnieje).
4. Sprawdź, czy żaden test nie zakłada sibling repo: grep `ak-bench-data` w `tests/`
   i `src/`; testy mają używać `tmp_path`, nie `data/` w repo.

**Kryterium akceptacji:** świeży klon bez `../ak-bench-data` przechodzi
`test_workspaces.py` (2) i `test_dataset_cli.py::test_dataset_validate_verifies_mutation`.

### A3. Test atlasu: `KeyError: LLM_ROUTER_UTILS_PLUGINS_PIPELINE` — ✅ NIE ISTNIEJE (test napisany poprawnie)

**Objaw:** `test_the_shipped_atlas_memory_experiment_declares_its_six_arms`
(`tests/unit/test_experiment_planner.py:544`) robi `variant.runtime_env[pipeline]`
dla każdego wariantu, ale ramiona `knowledge_enabled: false` w
`configs/experiments/knowledge-replay-atlas.yaml` celowo **nie mają** `runtime_env`
(brak pluginu w procesie = poprawny off).

**Zadania:**
1. Popraw test: dla ramion off asercja `pipeline not in variant.runtime_env`
   (lub `runtime_env` puste/brak klucza); dla ramion on asercja dokładnej wartości
   pipeline (`agentic_knowledge` / `agentic_routing_codex,agentic_knowledge`).
   Nie zmieniaj YAML-a ani plannera — to test jest błędny, nie implementacja.
2. Dodaj asercję negatywną: ramię off nie może ładować pluginu knowledge
   (to jest cała pointa testu wg jego docstringa).

**Kryterium akceptacji:** test zielony bez zmian w `knowledge-replay-atlas.yaml`.

### A4. Test live bez skipa

**Objaw:** `test_agent_run_reports_the_execution_plan` failuje bez `LLM_ROUTER_API_KEY`
zamiast się skipować.

**Zadania:**
1. Oznacz test `@pytest.mark.live` i dodaj skipif na brak `LLM_ROUTER_API_KEY`
   (konwencja już istnieje w `pyproject.toml`: markery `live`/`postgres`).
   Sprawdź wszystkie testy dotykające żywego routera/Codexa pod tym kątem
   (`grep -rn "LLM_ROUTER_API_KEY\|codex" tests/`).
2. Upewnij się, że `pytest` bez `AKBENCH_RUN_LIVE=1` / `AKBENCH_RUN_POSTGRES=1`
   nie próbuje łączyć się z siecią ani PostgreSQL.

**Kryterium akceptacji:** pełny suite bez env przechodzi; z env przechodzi też live.

### A5. `bench_ui` import wymaga hasła PostgreSQL

**Objaw:** `from bench_ui.app import create_app` na poziomie modułu (`bench_ui/app.py:501`)
tworzy `BenchDataService`, który rzuca `ConfigError` bez `AKBENCH_PG_PASSWORD`.
Import pakietu nie może wymagać działającej bazy.

**Zadania:**
1. Zrób inicjalizację `BenchDataService` leniwą (przy pierwszym requeście albo
   w `create_app()` z jawnym `database_url`), tak aby `import bench_ui` i kolekcja
   testów działały bez PostgreSQL. Błąd konfiguracji ma się pojawić przy starcie
   serwera (`akbench ui`), nie przy imporcie.
2. Test: `python -c "import bench_ui"` bez żadnego env musi się udać.

**Kryterium akceptacji:** `pytest --collect-only` działa bez `AKBENCH_PG_PASSWORD`;
`tests/unit/test_bench_ui*.py` zielone w trybie SQLite.

**Done Fazy A:** `pytest tests/unit tests/contract tests/integration tests/e2e -q`
= 0 failed na świeżym klonie (tylko skipy live/postgres). CHANGELOG: „Fixed”.

---

## FAZA C — Brakujące evaluatory (§16) — ✅ ZREALIZOWANA

Audyt: `diff_evaluator` i `static_analysis_evaluator` mają deskryptory, ale
`default_registry()` rejestruje tylko `pytest`+`command` i rzuca `EvaluatorNotFound`.

### C1. `DiffEvaluator` (`src/akbench/evaluators/diff.py`)

- Kontrakt `Evaluator` z `engine.py`: `evaluate(workspace, out_dir, timeout, reference_patch)`.
- Oblicz: `git diff` workspace vs reference patch → overlap (linie/funkcje),
  `result_kind: score`, verdict `partial` (nigdy `passed` samodzielnie — diff nie
  dowodzi poprawności, zgodnie z deskryptorem).
- Surowy diff zachowany w `raw`/`artifacts`. Brak reference patch → `evaluator_error`
  z powodem, nie zgadywanie.

### C2. `StaticAnalysisEvaluator` (`src/akbench/evaluators/static_analysis.py`)

- Konfigurowalny tool przez deskryptor (`ruff` domyślnie — już jest w dev deps;
  alternatywa: dowolna komenda z deskryptora). Parsuj JSON/text output do
  `passed/failed/skipped` + `score`.
- Działa w `evaluation_sandbox()` (poza workspace agenta), timeout, surowy output w `raw`.

### C3. Custom Python evaluator (`src/akbench/evaluators/python_evaluator.py`)

- Bezpieczne wykonywanie: osobny proces, timeout, brak sieci (docelowo Docker z opcjonalnej Fazy B; bez niej evaluator działa na hoście — nie udostępniaj obcego kodu),
  wejście = workspace + `out_dir`, wyjście = `EvaluationResult` (verdict + score + details).
- Rejestracja przez `default_registry(extra=[...])` już istnieje — dodaj gotowy
  przykład w `docs/EVALUATORS.md` i test z przykładowym evaluatorem w `tests/unit/`.

### C4. Rejestracja, testy, docs

1. `default_registry()` rejestruje wszystkie 5. Usuń komentarz „kinds have descriptors but
   no implementation here” (`src/akbench/evaluators/registry.py:70`).
2. Testy unit dla każdego (pass/partial/fail/timeout/evaluator_error) + test,
   że `diff` nigdy nie zwraca `passed`.
3. `docs/EVALUATORS.md` — rozdział na każdy evaluator: wejścia, wyjścia, verdicty,
   przykładowy YAML zadania.

**Kryterium akceptacji:** zadanie z `evaluator: diff_evaluator` i ze
`static_analysis_evaluator` przechodzi `dataset validate` + E2E; `evaluator list`
(w CLI, patrz D4) pokazuje 5 evaluatorów.

---

## FAZA D ✅ ZREALIZOWANA — Scheduler: concurrency, resume, cancel + brakujące komendy CLI (§15, §22)

Audyt: `concurrency` w YAML ignorowane (runy sekwencyjnie w
`src/akbench/cli/experiments.py::_run_experiment`), brak `experiment resume/cancel/show`,
brak `runtime start/stop/verify`.

### D1. Concurrency

1. `_run_experiment()` — wykonuj runy przez `ThreadPoolExecutor(max_workers=concurrency)`
   (agenci to procesy subprocess, więc wątki wystarczą; nie używaj multiprocessing).
   Każdy run ma własny workspace/sesję/kontener — izolacja już to gwarantuje.
2. Determinizm: wyniki zbierane i zapisywane w kolejności planu (nie kolejności
   zakończenia); logi oznaczone `run_uid`. `concurrency: 1` = dzisiejsze zachowanie.
3. Managed runtime: każdy run ma własną instancję (port ownership już istnieje
   w `runtime/llm_router.py`) — zweryfikuj, że N równoległych instancji nie koliduje
   (test integration z `concurrency: 2` na fake/runtime stub).
4. Planner już liczy `runs`; dodaj walidację: `concurrency > 1` wymaga
   `workspace_per_run: true` (już wymuszane) + ostrzeżenie w `plan` output.

### D2. Resume

1. `akbench experiment resume <uid>` — wczytaj plan z historii (`HistoryStore`:
   eksperyment + warianty + snapshoty), pomiń runy w stanie terminalnym
   (`completed/failed/timeout/...` wg `lifecycle.TERMINAL_STATES`), wykonaj resztę.
   Idempotentne: dwukrotny resume nie duplikuje runów (klucz: `run_uid` deterministyczny
   z `experiment_uid + variant_uid + task_uid + repetition` — sprawdź, czy dziś jest;
   jeśli nie, wprowadź i zmigruj).
2. Resume po przerwaniu (Ctrl+C): SIGINT oznacza runy w toku jako `cancelled`,
   resume je ponawia. Test: symulowane przerwanie + resume = pełna macierz bez duplikatów.

### D3. Cancel

1. `akbench experiment cancel <uid>` — dla trwającego eksperymentu: token anulowania
   przekazywany do orchestratora → `AgentAdapter.cancel()` (już istnieje w kontrakcie)
   → stan `cancelled`, artefakty zachowane, runtime zatrzymany.
2. Dla CLI jednorazowego (`run single`, `agent run`): obsłuż SIGINT/SIGTERM
   i propaguj cancel do agenta/runtime (dziś timeout już to robi w `codex.py` —
   uogólnij na orchestrator).

### D4. Brakujące komendy CLI (wyrównanie do §22)

| Komenda z planu | Implementacja |
|---|---|
| `experiment show <uid>` | nowy: deskryptor + warianty + runy + metryki z historii (użyj `reporting/data.py`) |
| `runtime start/stop` | dla `managed`: start/stop instancji spoza runu (do ręcznej weryfikacji); dla `external`: jawny błąd „nie można zarządzać external” |
| `runtime verify` | `healthcheck` + `read_configuration` + porównanie z oczekiwaną (użyj `RuntimeManager.verify_configuration`) |
| `runtime status` | alias do `runtime state` (zachowaj obie nazwy) |
| `evaluator list` | nowy (lub w `descriptor list`): lista zaimplementowanych evaluatorów z rejestru |
| `experiment resume/cancel` | patrz D2/D3 |

Zaktualizuj `docs/CLI.md` (tabela komend plan vs implementacja) i docstring
`src/akbench/cli/main.py` (usuń „intentionally absent”).

**Kryterium akceptacji:** `concurrency: 2` działa E2E; resume po przerwaniu nie duplikuje;
cancel zostawia artefakty i stan `cancelled`; wszystkie komendy z §22 istnieją
(albo są udokumentowane jako aliasy).

---

## FAZA E ✅ ZREALIZOWANA — Environment Descriptor (§9) + mapowanie struktury (§5.1)

### E1. Nowy kind `environment`

1. `src/akbench/descriptors/environment.py` — model: `id`, `version`, `os`, `python`,
   `tools[]`, `network`, `filesystem`, `sandbox` (host/docker), `limits`.
2. `DescriptorKind.ENVIRONMENT`, rejestracja w `DESCRIPTOR_MODELS`, katalog
   `descriptors/environments/` z min. 2 deskryptorami: `local-host.yaml`,
   `docker-python312.yaml`.
3. Planner: eksperyment może wskazać `environment: <id>`; walidacja sprawdza
   istnienie + kompatybilność z `isolation.sandbox` (opcjonalna Faza B — jeśli pominięta, `sandbox` to tylko `host`). Snapshot środowiska
   w manifeście runu (obok `sandbox_image`).
4. Testy: walidacja deskryptora, nieznane środowisko blokuje plan, digest w snapshocie.

### E2. Struktura katalogów §5.1 (bez refaktoru)

Nie przenoś plików. W `docs/ARCHITECTURE.md` (Faza K) dodaj tabelę mapowania:
planowana ścieżka → rzeczywista ścieżka → odpowiedzialność (np.
`repositories/` → `datasets/repository.py`, `sandbox/` → `evaluators/isolation.py`
+ `sandbox/` z opcjonalnej Fazy B (jeśli wdrożona), `observability/` → `metrics/` + `plugins/` + tabele `*_observations`).
Jeśli brakuje modułu z realną luką funkcjonalną (nie tylko nazwą), załóż go
jako cienki pakiet re-eksportujący (np. `src/akbench/categories/__init__.py`
re-eksportuje `descriptors/category.py`) — tylko tam, gdzie to usuwa lukę.

**Kryterium akceptacji:** `descriptor validate` przechodzi z kind `environment`;
eksperyment z nieistniejącym środowiskiem jest odrzucany na etapie `validate`.

---

## FAZA F ✅ ZREALIZOWANA — Drugi agent i klasy agentów (§6.5, §25A)

Audyt: tylko `codex` (process). Framework gotowy, ale `agent_comparison` nieużywalny.

### F1. Agent `fake` (deterministyczny, do CI i porównań)

1. Promuj `tests/contract/fake_agent.py` do `src/akbench/agents/fake.py`
   (`adapter_id: fake`, deskryptor `descriptors/agents/fake.yaml`):
   deterministyczne zachowanie (np. kopiuje rozwiązanie z `tests/fixtures/*_solution/`
   albo stosuje zadaną strategię: `solve` / `noop` / `fail` / `timeout` przez config).
   Capabilities: wszystkie `verified` (bo to nasz własny protokół), `cost_usage: unsupported`.
2. Rejestracja w `agents/catalog.py` + `agents/registry.py` bez zmian w runnerze.
3. Testy kontraktowe `tests/contract/test_fake_agent_contract.py` już istnieją —
   przenieś/rozszerz o nowy adapter (ten sam zestaw z §6.8).

### F2. Agent HTTP/API (`src/akbench/agents/http.py`)

- Adapter dla agentów dostępnych przez HTTP (protokół AK-Bench, nie wymyślony
  endpoint konkretnego produktu): `POST /tasks`, `GET /sessions/{id}`,
  `POST /sessions/{id}/cancel`, `GET /sessions/{id}/result` — to **protokół
  AK-Bench dla adaptera HTTP**, udokumentowany w `docs/AGENT_ADAPTERS.md` jako
  kontrakt, który serwer agenta musi spełnić. Jeśli żaden realny agent go nie ma,
  adapter służy jako referencyjna implementacja klasy „agent API” + testy na
  stub-serwerze (`tests/contract/stubs/`).
- Capabilities: `workspace_binding: partial` (workspace po stronie serwera),
  `token_usage/cost_usage: unsupported` domyślnie, `cancellation: verified`.
- Nie implementuj fikcyjnych endpointów pod konkretny produkt bez weryfikacji
  w jego dokumentacji (zasada §29.10).

### F3. Agent comparison end-to-end

1. Nowy `configs/experiments/agent-comparison.yaml` (`type: agent_comparison`):
   `codex` vs `fake` (i/lub `http`) na tym samym datasecie, te same evaluatory.
2. Planner: dla `agent_comparison` sprawdź przecięcie capabilities agentów;
   różnice oznacz w raporcie (już jest mechanizm `unverified/unsupported`).
3. Raport: strona porównania agentów (już istnieje `agents/index.html` — dodaj
   widok side-by-side dla eksperymentu `agent_comparison`).

**Kryterium akceptacji:** `experiment run agent-comparison.yaml` przechodzi E2E
z 2 agentami; dodanie trzeciego agenta = 1 deskryptor + 1 adapter + testy,
bez dotykania `orchestration/`, `experiments/`, `evaluators/`.

---

## FAZA G — Mierzenie metryk knowledge (§18.4)

Audyt: wszystkie 8 metryk knowledge (`write_count`, `retrieval_count`, `hit_rate`,
`retrieval_latency`, `utilization`, `false_positive_retrieval`, `indexing_latency`,
`size`) to `availability: unavailable` — poprawnie, bo router nie eksportuje sygnałów.
Zadaniem fazy jest **dowieźć sygnały z weryfikowalnych źródeł**, nie wymyślić API.

### G1. Kolektory z `router.log` (managed instance)

1. `src/akbench/plugins/knowledge_metrics.py` (nowy) — parser logu instancji
   zarządzanej (`router.log`, verbose mode już używany w `llm_router.py`):
   wyciągnij zdarzenia zapisu/odczytu wiedzy, jeśli log je zawiera (zweryfikuj
   format na prawdziwym logu z `spike/evidence/` i testów live; format zapisz
   w `docs/ROUTER_INTEGRATION.md`).
2. Mapowanie na metryki: `knowledge_write_count`, `knowledge_retrieval_count`,
   `knowledge_retrieval_latency` (z timestampów), `knowledge_size` (jeśli log
   zawiera rozmiar KB). Każda metryka dostaje `source: log` w `ValueSource`.
3. Gdy log nie zawiera zdarzenia: metryka zostaje `unavailable` z powodem
   (nie 0). Testy: parser na fixture-logach (pass + brak zdarzeń + uszkodzona linia).

### G2. Gotowość KB i indexing latency

1. Rozszerz `knowledge/readiness.py`: oprócz dzisiejszego gate, mierz czas
   `write → indexed` gdy źródło (log/plik KB instancji zarządzanej) jest dostępne.
   Na instancji external bez readbacku: `unavailable` (jak dziś).
2. `knowledge_indexing_latency` i `knowledge_size` przechodzą z `unavailable`
   na `computed` **tylko** dla lifecycle `managed` z dowodem w logu/plikach.

### G3. Retrieval vs utilization (rozdzielenie z §17)

1. `knowledge_utilization`: korelacja wstrzykniętej wiedzy (z logu routera)
   z tool calls agenta (z `agent_trace.jsonl` / `tool_calls.jsonl` z `codex.py`).
   Korelacja po `session_id` + oknie czasowym. Brak korelacji = `unavailable`.
2. `knowledge_false_positive_retrieval`: wymaga ground truth — oznacz
   `unavailable` z powodem, dopóki zadanie nie zadeklaruje `relevant_knowledge`
   w `task.yaml` (dodaj opcjonalne pole + walidację; stare zadania bez pola = unavailable).

### G4. Raportowanie

`metrics/collect.py` + `reporting/data.py`: metryki knowledge w raporcie
z kolumną `source` i `availability`. Dashboard nie pokazuje `unavailable` jako 0.

**Kryterium akceptacji:** na managed instance z verbose logiem co najmniej
`write_count` + `retrieval_count` są `computed` z dowodem w teście E2E;
na external bez sygnałów nadal `unavailable` (test negatywny).

---

## FAZA H ✅ ZREALIZOWANA — Brakujące przykłady eksperymentów (§25 C, E, A)

### H1. Auto Codex ON/OFF (przykład C)

Nowy `configs/experiments/auto-codex-on-off.yaml`: jeden agent, jeden model,
czynnik `routing_heuristic_enabled` / `routing_semantic_enabled` (deskryptory już
istnieją w `descriptors/dimensions/`), runtime managed, pipeline z
`agentic_routing_codex`. Rejestruj faktycznie użyte modele (`routed_model`).

### H2. Pełna macierz 12 wariantów (przykład E)

Nowy `configs/experiments/full-matrix-12.yaml` (obok istniejącego `full-matrix.yaml`,
który jest dziś `strategy: custom_matrix`, nie full_factorial):
Knowledge ON/OFF × Auto Codex ON/OFF × Model A/B/C = 12 wariantów,
`strategy: full_factorial`. Modele A/B/C = 3 wartości z `descriptors/dimensions/model.yaml`
(`qwen/Qwen3.8-27B`, `qwen/Qwen3.8-Flash-Next`, `auto_codex` jako alias routingu —
z komentarzem, że alias to decyzja per-request). Każdy wariant z własnym
`runtime_env` (pipeline). `limits.max_runs` ustawione świadomie.

### H3. Agent comparison (przykład A)

`configs/experiments/agent-comparison.yaml` z Fazy F3.

### H4. Strażnik shipped YAML-i

Test `tests/unit/test_shipped_experiments.py` (nowy): każdy YAML w
`configs/experiments/` przechodzi `load_experiment_file` + `planner.plan()`
bez błędów (bez uruchamiania agentów). Nowy eksperyment bez tego testu nie przechodzi CI.

**Kryterium akceptacji:** `akbench experiment validate` + `plan` zielone dla
wszystkich YAML-i w `configs/experiments/`; `full-matrix-12` planuje dokładnie 12 wariantów.

---

## FAZA I — Export: wyłączalne prompty/diffy/trace'y (§21) ✅ ZREALIZOWANA

Audyt: redakcja sekretów automatyczna (`export/redact.py`), brak flag wyłączania.

### I1. Opcje eksportu

`akbench export experiment <uid> --format json|csv|html [--no-prompts] [--no-diffs] [--no-traces] [--include-artifacts]`
- `--no-prompts`: usuń `final_message`, prompty z trace'y (zastąp `[redacted]`).
- `--no-diffs`: pomiń `diff.patch` i pola diff w JSON.
- `--no-traces`: pomiń `agent_trace.jsonl` / `tool_calls.jsonl` (zostaw metryki).
- Domyślnie: dzisiejsze zachowanie (redakcja sekretów zawsze, bez flag).

### I2. Testy

Unit: każda flaga usuwa dokładnie to, co deklaruje; sekrety nadal redagowane
nawet bez flag. E2E: eksport z flagami przechodzi walidację schematu JSON.

**Kryterium akceptacji:** `export --help` dokumentuje flagi; testy zielone;
`docs/EXPORT.md` zaktualizowane.

---

## FAZA J ✅ ZREALIZOWANA — Baza domyślna: SQLite (§5, §27) + porządek z `bench_ui`

Audyt: plan mówi SQLite, repo domyślnie PostgreSQL (odstępstwo udokumentowane,
ale niezgodne z §27 MVP). Decyzja: **wróć do SQLite jako domyślnej** (zgodność z planem),
PostgreSQL zostaje jako opt-in (już zaimplementowany).

### J1. Domyślna baza

1. `configs/defaults.yaml` + `config/models.py`: `backend: sqlite` domyślnie,
   ścieżka `data/akbench.sqlite` (zgodnie ze strukturą §5.1). PostgreSQL przez
   `AKBENCH_DB_BACKEND=postgres` + `AKBENCH_PG_*` (jak dziś).
2. `README.md`, `.env.example`, `docs/STORAGE.md`: zaktualizuj — SQLite to
   domyślny tryb lokalny, Postgres to tryb współdzielony.
3. Migracja: istniejące instalacje na Postgres nie tracą danych (konfiguracja
   jawnie wskazuje backend; brak automatycznej migracji wstecznej).

### J2. `bench_ui` jako dodatek, nie podstawa

1. Potwierdź w `docs/ARCHITECTURE.md`: podstawowym interfejsem jest CLI + statyczny
   HTML (§5), `bench_ui` (FastAPI) to opcjonalny dashboard. `akbench ui` startuje
   go na żądanie; brak UI nie blokuje benchmarku.
2. Po Fazie A5 import `bench_ui` nie wymaga bazy — zweryfikuj testami.

**Kryterium akceptacji:** świeży klon: `akbench init && akbench doctor` działa
bez PostgreSQL i bez `.env`; `pytest` zielony w trybie domyślnym.

---

## FAZA K — Dokumentacja (§28): brakujące 11 plików

Każdy plik: opisuje **tylko istniejącą** implementację (po Fazach A–J), z przykładami
YAML/kodu zgodnymi z kodem. Szablon: cel, pojęcia, format, przykłady, ograniczenia.

| Plik | Zawartość (źródła w kodzie) |
|---|---|
| `docs/ARCHITECTURE.md` | Diagram §3 + tabela mapowania modułów (§5.1 → realne ścieżki, z Fazy E2) + zasady §2 + rola `bench_ui` |
| `docs/RUNTIME_ADAPTERS.md` | Kontrakt `RuntimeManager`, lifecycle managed/external, `factor_env`, weryfikacja modelu z logu (`runtime/llm_router.py`) |
| `docs/TASK_FORMAT.md` | `task.yaml` (wszystkie pola z `datasets/task.py`), `repository.yaml` w zadaniu, `parts.json`, hidden/public tests |
| `docs/CATEGORY_SYSTEM.md` | Category Descriptor, 9 kategorii, trudności, `task_requirements`, dodawanie kategorii bez zmian w silniku |
| `docs/EXPERIMENT_DESCRIPTORS.md` | `ExperimentBody` (wszystkie bloki z `experiments/descriptor.py`), walidacja §12.1, limity |
| `docs/DIMENSION_DESCRIPTORS.md` | 9 typów wymiarów, `source`, controllability, `factor_env` mapowanie, przykłady |
| `docs/EXPERIMENT_TYPES.md` | `configuration` / `agent_comparison` / `knowledge_replay` / `model_comparison` — kiedy który, co walidator odrzuca |
| `docs/FACTORIAL_DESIGN.md` | 5 strategii (`experiments/strategies.py`), baseline, deduplikacja, szacowanie skali |
| `docs/ISOLATION_AND_SECURITY.md` | Model zagrożeń, worktree, Docker (opcjonalna Faza B — oznaczona jako `deferred`, jeśli pominięta), hidden tests, sekrety, manifesty, granice (co AK-Bench **nie** gwarantuje) |
| `docs/AGENT_ADAPTERS.md` *(rozszerz)* | Dodaj adaptery `fake` i `http` (Faza F) + protokół HTTP |
| `docs/EVALUATORS.md` *(rozszerz)* | 5 evaluatorów (Faza C) |

Plus: `docs/CLI.md` — tabela komend plan (§22) vs implementacja (po Fazie D4),
zaznacz aliasy. `README.md` — sekcja „Zgodność z planem” z linkiem do audytu.

**Kryterium akceptacji:** wszystkie 23 pliki z §28 istnieją; każdy przykład YAML
w docs przechodzi walidację odpowiedniego loadera (test `test_docs_examples.py` —
wyciągnij bloki `yaml` z docs i waliduj; skip dla fragmentów oznaczonych `fragment`).

---

## FAZA L — Weryfikacja końcowa „100%”

### L1. Checklist §1–30 (każdy punkt: test lub dokument jako dowód)

Przejdź sekcja po sekcji planu źródłowego i dla każdej dopisz w audycie
(`AK-Bench-audyt-planu.md`, zaktualizowany) status + dowód (plik/test).
Żaden punkt nie może zostać „✅ bez dowodu”.

### L2. Pełna macierz testów na świeżym klonie

```bash
git clone <repo> /tmp/fresh && cd /tmp/fresh
# bez ../ak-bench-data, bez PostgreSQL, bez kluczy API:
AKBENCH_DB_BACKEND=sqlite python -m pytest tests/unit tests/contract tests/integration tests/e2e -q
akbench init && akbench doctor
akbench descriptor validate && akbench dataset validate
for f in configs/experiments/*.yaml; do akbench experiment validate "$f" && akbench experiment plan "$f"; done
akbench experiment run configs/experiments/wordcount-direct-sanity.yaml  # E2E na fake
akbench report all && akbench export experiment <uid> --format json
```

Wszystko zielone. Testy `live`/`postgres` skipują się bez env.

### L3. Rezultat końcowy §30 (12 punktów) — demonstracja

Na czystej instalacji wykonaj i udokumentuj (screenshot/log w `docs/` lub CHANGELOG):
dodaj dataset → wybierz agenta → tryb direct/runtime → modele/pluginy →
YAML eksperymentu → validate/plan → run → metryki → ocena → porównanie →
raport HTML → eksport. Każdy krok z §30 musi mieć działającą komendę.

### L4. Release

- Bump wersji (`.version`, `pyproject.toml`, `CHANGELOG.md`), tag `vX.Y.Z`.
- `CHANGELOG.md`: sekcja „100% zgodności z planem” z listą zamkniętych braków (Fazy A, C–K; Faza B opcjonalna — jeśli wdrożona, dopisz ją osobno).
- Zamknij audyt: zaktualizuj `AK-Bench-audyt-planu.md` — wszystkie wiersze ✅ z dowodami.

**Kryterium akceptacji:** L2 w pełni zielone na świeżym klonie; checklist §13
w 100% zaznaczona; `akbench doctor` raportuje `ok` dla wszystkich wymaganych checków.

---

## FAZA B — Izolacja Docker (§5, §14, §23, §27) — ⚠️ OPCJONALNA / OPTIONAL (ostatnia faza — można pominąć)

> **Status: OPCJONALNA / OPTIONAL — ostatnia faza planu, NIE blokuje osiągnięcia 100%.**
> Docker jest celowo odłożony na koniec: izolacja hostowa (worktree + `CODEX_HOME` +
> `sandbox_mode` Codexa + sandbox ewaluacyjny) w pełni wystarcza do lokalnych,
> badawczych eksperymentów. Fazę B wdrażaj dopiero, gdy: uruchamiasz niezaufanych
> agentów, współdzielisz maszynę/CI, potrzebujesz odtwarzalności między maszynami
> albo publikujesz wyniki z gwarancją środowiska. Jeśli faza zostanie pominięta:
> w `docs/ISOLATION_AND_SECURITY.md` i CHANGELOG oznacz ją jawnie jako `deferred`,
> raportuj `sandbox: host`, a `sandbox_image` w manifeście zostaje `unknown`
> (uczciwie, bez zgadywania). Faza L (weryfikacja 100%) jest wykonywana **bez** Fazy B.

Audyt: Docker nie istnieje w kodzie (tylko opcjonalny check w `doctor`).
Izolacja to dziś: worktree + kopia sandboxa ewaluacyjnego + `CODEX_HOME` + `sandbox_mode` Codexa.
` sandbox_image` w manifeście zawsze `unknown`.

### B1. Projekt `DockerSandbox`

**Nowe pliki:**
- `src/akbench/sandbox/__init__.py`, `docker.py` — klasa `DockerSandbox`:
  `create(workspace, image, network="none", read_only=True, limits, env_allowlist)`,
  `exec(cmd, timeout)`, `destroy()`. Wyłącznie `docker run` przez subprocess
  (bez nowej zależności SDK, chyba że `docker` SDK już jest — sprawdź `pyproject.toml`).
- `src/akbench/sandbox/config.py` — model Pydantic: `image`, `network`, `cpus`,
  `memory`, `read_only_rootfs`, `tmpfs`, `user`, `cap_drop: ["ALL"]`.
- `descriptors/environments/docker.yaml` (patrz Faza E) — deskryptor środowiska.

**Zasady:** sieć domyślnie `none` (wyjątek tylko gdy runtime tego wymaga, jawnie
w deskryptorze); filesystem read-only poza workspace i `/tmp`; brak dostępu do
`~/.ssh`, `/data`, katalogu projektu (montujemy **tylko** workspace); timeout = kill
kontenera; każdy run = nowy kontener (brak reuse).

### B2. Integracja z istniejącymi ścieżkami

1. `WorkspaceManager.prepare()` — bez zmian (worktree zostaje). Docker dokłada
   warstwę wykonania **wewnątrz** workspace, nie zastępuje worktree.
2. `evaluators/isolation.py` — `evaluation_sandbox()` dostaje tryb `docker`:
   hidden tests montowane do kontenera tylko na czas ewaluacji, nigdy do workspace agenta.
3. `orchestration/orchestrator.py` — nowa opcja `isolation: {sandbox: host|docker, image: …}`
   w `ExperimentBody.isolation` (`experiments/descriptor.py`). `host` = dzisiejsze
   zachowanie (wsteczna kompatybilność); `docker` = agent i/lub evaluator w kontenerze.
4. `doctor.py` — check `docker` staje się wymagany tylko gdy eksperyment deklaruje
   `sandbox: docker`; w przeciwnym razie warning (jak dziś).

### B3. Manifest i fallback

1. `storage/manifest.py` — `sandbox_image` wypełniane z deskryptora środowiska
   (obraz + digest, jeśli dostępny). Gdy `sandbox: docker` a Docker niedostępny:
   run kończy się `infrastructure_error` (nie cichym fallbackiem na host).
2. `configs/defaults.yaml` — sekcja `sandbox:` z domyślnym obrazem (np. `python:3.12-slim`
   + pytest) i limitami. Obraz musi być pullowalny i mieć pytest dla evaluatora.

### B4. Testy i dokumentacja

- Unit: budowanie argv `docker run` (flagi sieci/RO/limitów), allowlist env.
- Integration (skip bez Dockera): agent w kontenerze nie widzi hidden tests,
  nie ma sieci, nie widzi `/data`; evaluator w kontenerze widzi hidden tests.
- `docs/ISOLATION_AND_SECURITY.md` (Faza K) opisuje model zagrożeń i granice.

**Kryterium akceptacji:** eksperyment z `sandbox: docker` przechodzi E2E
(wordcount sanity) w kontenerze; manifest zawiera `sandbox_image`; bez Dockera
błąd jest jawny (`infrastructure_error`), nie cichy.

---

---

## 13. Checklist końcowa (do odhaczania przez agenta)

### Defekty (Faza A)
- [x] A1 `parts/*.patch` w git + strażnik integralności datasetu (parts w git od `6102769`; strażnik `tests/unit/test_dataset_integrity.py` — 9 passed)
- [x] A2 brak symlinka `data`, świeży klon działa bez sibling repo (symlink `git rm`, katalogi `data/*` tworzone leniwie; README Quick start zaktualizowany)
- [x] A3 test atlasu naprawiony (off = brak pipeline) — defekt nie istniał w bieżącym kodzie; `test_the_shipped_atlas_memory_experiment_declares_its_six_arms` asercjonuje `runtime_env.get(pipeline, "")` i przechodzi (39/39 w `tests/unit/test_experiment_planner.py`)
- [x] A4 testy live skipują się bez kluczy — `tests/unit tests/contract` zielone bez env (0 failed, 4 skipped); `test_codex_live_contract.py` ma skipif na `AKBENCH_RUN_LIVE`, `test_agent_run_reports_the_execution_plan` używa `codex_stub.py` i nie wymaga `LLM_ROUTER_API_KEY`
- [x] A5 `import bench_ui` bez bazy — `python -c "import bench_ui.app"` działa bez `AKBENCH_DB_BACKEND`/`AKBENCH_PG_PASSWORD`; `BenchDataService.__init__` łapie `ConfigError` do `self.config_error` (bench_ui/service.py:683-710); `create_app()` raportuje, nie rzuca

### Funkcjonalność (Fazy C–J)
- [x] C 5 evaluatorów zarejestrowanych i przetestowanych — `DiffEvaluator`, `StaticAnalysisEvaluator`, `PythonEvaluator` w `src/akbench/evaluators/`; `default_registry()` → 5 (`pytest`, `command`, `diff`, `static_analysis`, `python`); `tests/unit/test_evaluators_supplementary.py` (11) + `test_evaluators.py` (test równości kindów z rejestrem) + 3 testy E2E CLI w `tests/integration/test_evaluate_cli.py`; `akbench evaluate task` przyjmuje `--reference-patch/--script/--command`; docs `docs/EVALUATORS.md` z sekcją o każdym. Diff nigdy nie zwraca `passed` (test).
- [x] D concurrency, resume, cancel, `experiment show`, `runtime start/stop/verify/status`, `evaluator list` — `concurrency` z `execution_policy` realizowany przez `ThreadPoolExecutor` w `src/akbench/cli/experiments.py::_run_experiment` (wyniki w kolejności planu, `--concurrency` nadpisuje, ostrzeżenie `concurrency_above_one` w planie); `experiment resume UID` (klucz komórki: task+variant+repetition z historii, `cancelled` się ponawia, drugi resume = zero runów); `experiment cancel UID` + SIGINT/SIGTERM w `run single`/`agent run` przez `CancelToken`/`FileCancelSource` (`src/akbench/orchestration/cancellation.py`), run kończy się `cancelled` z zachowanymi artefaktami; `PREPARE_LOCK` w `datasets/workspace.py` (git worktree na współdzielonym bare cache); nowe komendy `experiment show`, `runtime start/stop/verify/status`, `evaluator list`; testy: `tests/unit/test_cancellation.py` (7), 3 testy cancel w `tests/integration/test_orchestrator.py`, `tests/integration/test_experiment_scheduler_cli.py` (5, w tym cancel procesu przez marker); `docs/CLI.md` z tabelą plan vs implementacja
- [x] E kind `environment` + deskryptory + walidacja w plannerze — `src/akbench/descriptors/environment.py` (`EnvironmentBody`: os/python/tools/network/filesystem/sandbox/image/limits; docker wymaga image, host go odrzuca), `DescriptorKind.ENVIRONMENT` + rejestracja w `DESCRIPTOR_MODELS`, katalog `descriptors/environments/` (`local-host.yaml`, `docker-python312.yaml`); `experiment.environment: <id>` w `experiments/descriptor.py`, walidacja `_check_environment` w plannerze (`environment_unknown`, `environment_sandbox_unavailable` — Faza B nie istnieje, więc docker jest odrzucany, a nie udawany), digest w `descriptor_snapshots`, snapshot środowiska w rekordzie runu i w manifeście obok `sandbox_image` (`orchestration/lifecycle.py`, `storage/manifest.py`); E2 = tabela mapowania §5.1 w `docs/ARCHITECTURE.md` → Faza K (tu bez przenosin plików); testy: `tests/unit/test_environment_descriptor.py` (5) + 6 testów plannera (walidacja, nieznane środowisko, docker, concurrency warning) + E2E manifestu w `tests/integration/test_experiment_scheduler_cli.py`; docs: `docs/DESCRIPTOR_SYSTEM.md`, `docs/EXPERIMENTS.md`, `docs/STORAGE.md`
- [ ] F agenci `fake` + `http`, `agent-comparison.yaml` E2E
- [ ] G metryki knowledge mierzone z logu managed (min. write/retrieval count), `unavailable` bez sygnałów
- [ ] H `auto-codex-on-off.yaml`, `full-matrix-12.yaml` (12 wariantów), strażnik shipped YAML-i
- [x] I flagi eksportu `--no-prompts/--no-diffs/--no-traces` (`src/akbench/export/filters.py`: `ExportFilters`, `filter_document`, `filter_payload`;
- [ ] J SQLite domyślnie, Postgres opt-in, `init/doctor` bez `.env`

### Dokumentacja i release (Fazy K–L)
- [ ] K wszystkie 23 pliki z §28 + test przykładów z docs
- [ ] L1 checklist §1–30 planu źródłowego z dowodami w audycie
- [ ] L2 pełna macierz testów zielona na świeżym klonie
- [ ] L3 demonstracja 12 punktów §30
- [ ] L4 wersja + CHANGELOG + tag

### OPCJONALNE — Faza B (Docker), ostatnia, NIE blokuje 100%
- [ ] B Docker sandbox (agent + evaluator), `sandbox_image` w manifeście, jawny błąd bez Dockera
- [ ] B (jeśli pominięta) oznaczona jako `deferred` w docs/CHANGELOG, raportowane `sandbox: host`

---

## Załącznik: mapa braków z audytu → fazy

| Brak z audytu | Faza |
|---|---|
| `parts/*.patch` ignorowane przez `.gitignore` | A1 |
| Dangling symlink `data` | A2 |
| Test atlasu `KeyError` | A3 |
| Test live bez skipa | A4 |
| `bench_ui` wymaga PG przy imporcie | A5 (+J2) |
| Brak izolacji Docker | **B — OPCJONALNA / OPTIONAL (ostatnia, można pominąć)** |
| `diff`/`static`/`custom` evaluatory bez implementacji | C |
| Brak schedulera (resume/cancel/concurrency) | D1–D3 |
| Brak `experiment show`, `runtime start/stop/verify` | D4 |
| Brak Environment Descriptor | E1 |
| Struktura §5.1 vs realna (nazwy modułów) | E2 + K |
| Tylko 1 agent, brak klas HTTP/API/service | F |
| Metryki knowledge wszystkie `unavailable` | G |
| Brak przykładów C (Auto Codex), E (12 wariantów), A (agenci) | H (+F3) |
| Brak flag eksportu promptów/diffów | I |
| Domyślny Postgres zamiast SQLite | J1 |
| `bench_ui` SPA ponad plan | J2 (udokumentować jako dodatek) |
| 11 brakujących plików docs | K |
| Brak dowodu 100% (checklist, świeży klon, §30) | L |
