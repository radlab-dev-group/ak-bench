# AK-Bench — audyt zgodności z `AK-Bench-implementation-plan.md`

**Repo:** `radlab-dev-group/ak-bench` @ `125535b` (Merge PR #16), wersja `0.1.1`
**Data audytu:** 2026-11-10 · Metoda: klon repo, lektura planu (§1–30), mapowanie na kod,
uruchomienie testów (`AKBENCH_DB_BACKEND=sqlite`).

> **Aktualizacja 2026-11-11 (przegląd zgodności z kodem):** audyt opisuje stan `125535b`.
> Od tego commitu weszła memory suite (`f7da55b`, 13 nowych zadań): `datasets/` ma 35 zadań
> (20 bug_fix + 15 new_feature), `configs/experiments/` ma 10 YAML-i, `tests/unit+contract`
> przechodzi 619 testów (0 błędów, 4 skipy live/postgres). Defekt 3 (`KeyError` w teście
> atlasu) i 4 (test live bez skipa) **nie istnieją w bieżącym kodzie** — patrz §4.

## Werdykt w skrócie

**Plan jest w praktyce zrealizowany — wszystkie fazy 0–13 mają działającą implementację,
a MVP z §27 jest spełnione, miejscami z nadwyżką.** Nie jest to jednak 100%:
pozostały konkretne braki (Docker, 3 z 5 evaluatorów, scheduler, drugi agent,
Environment Descriptor, 11 plików dokumentacji) oraz 3 defekty powodujące
błędy testów na świeżym klonie. Szczegóły poniżej.

---

## 1. Fazy implementacji (§26) — status

| Faza | Done wg planu | Status | Dowód w repo |
|---|---|---|---|
| 0 Spike | prototyp + `AGENT_INTEGRATION.md` + `ROUTER_INTEGRATION.md` | ✅ | `spike/` (runner, evidence), `docs/AGENT_INTEGRATION.md`, `docs/ROUTER_INTEGRATION.md` |
| 1 Szkielet | `akbench doctor`, init, migracje | ✅ | `cli/main.py` (`init/doctor`), `bootstrap.py`, Alembic 0001–0010 |
| 2 Deskryptory i registry | agent+plugin bez zmian w silniku | ✅ | `descriptors/` (8 kindów), `src/akbench/descriptors/`, `docs/DESCRIPTOR_SYSTEM.md` |
| 3 Dataset i repozytoria | powtarzalne workspace | ✅ | `datasets/` (35 zadań na `f7da55b`; 22 na `125535b`), `datasets/workspace.py` (git worktree), `verification.py` |
| 4 Agent Adapter Framework | Codex przez adapter, runner bez kodu Codexa | ✅ | `agents/contract.py` (Protocol 1:1 z §6.2), `agents/codex.py` (736 linii, jedyne miejsce z logiką Codexa), `tests/contract/` |
| 5 Runtime Manager | direct/runtime/router | ✅ | `runtime/contract.py` (`ExecutionMode`, `RuntimeManager` 1:1 z §7.2), `runtime/llm_router.py`, tryby `managed`+`external` |
| 6 Evaluator Engine | niezależna ocena | ⚠️ częściowo | `pytest_evaluator` + `command_evaluator` działają; `diff`/`static_analysis`/`python` tylko deskryptory (patrz §3) |
| 7 Orchestrator i Scheduler | stabilna seria runów | ⚠️ częściowo | lifecycle 1:1 z §15 (`orchestration/lifecycle.py`), retry infra, timeout/cancel sesji; **brak schedulera** (resume/cancel/concurrency) |
| 8 Experiment + Planner | plan bez uruchamiania | ✅ | `experiments/planner.py` (924 linie), wszystkie 5 strategii, baseline, limity `max_runs` |
| 9 Plugin + Observability | weryfikacja pluginów | ✅ | `plugins/`, `descriptors/env.py`, statusy `verified/unverified/mismatch/unsupported/not_configured/runtime_error` |
| 10 Knowledge Replay | poprawny eksperyment pamięciowy | ✅ | `knowledge/` (modes, planning, readiness gate, fingerprint, isolation), eksperymenty knowledge-replay* (4 na `f7da55b`) |
| 11 Storage i Metrics | pełna historia | ✅ | 19 tabel (wszystkie 16 z §19 + `agents/runtimes/task_files`), `metrics/aggregate.py` z formułami §18 |
| 12 Reporting | statyczny HTML | ✅ | `reporting/render.py` (3059 linii) — index, eksperymenty, warianty, zadania, agenci, runtime'y, pluginy, modele, runy, artefakty |
| 13 Export i stabilizacja | regularne eksperymenty | ✅ | `export/` (JSON/CSV/HTML + redakcja sekretów), testy E2E YAML→HTML, reproducibility |

## 2. Mapowanie sekcji planu (§1–30)

| Sekcja | Status | Uwagi |
|---|---|---|
| §1 Cel, zasada wymiennego agenta | ✅ | Orchestrator/evaluator/planner nie znają Codexa (grep: 0 trafień poza komentarzem); Codex tylko w `agents/codex.py` + deskryptorze |
| §2 Zasady 1–12 | ✅ | Wszystkie egzekwowane strukturalnie (capability gating, triada requested/effective/observed, `unsupported/unverified` zamiast atrap) |
| §3 Architektura, moduły | ✅ z przemianowaniami | Brak osobnych modułów: `categories/`, `repositories/`, `mutations/`, `discovery/`, `sandbox/`, `runner/`, `observability/` — ich odpowiedzialność jest w `datasets/`, `descriptors/registry.py`, `evaluators/isolation.py`, `orchestration/`, `metrics/`+`plugins/` |
| §4 Spike | ✅ | Patrz Faza 0 |
| §5 Stos technologiczny | ⚠️ | Python 3.12+, Pydantic, YAML, Typer, SQLAlchemy, Alembic, pytest, worktrees, Jinja2, Chart.js (bench_ui), JSON/JSONL — ✅. **Docker: brak** (tylko opcjonalny check w `doctor`). **Baza: domyślnie PostgreSQL, nie SQLite** (odstępstwo udokumentowane w README/CHANGELOG; SQLite nadal działa przez `AKBENCH_DB_BACKEND=sqlite`) |
| §5.1 Struktura katalogów | ⚠️ | Zasadniczo zgodna; różnice jak w §3 + `bench_ui/` (FastAPI) spoza planu |
| §6 Agenci (registry, adapter, wynik, capabilities, deskryptor, testy kontraktowe) | ✅ | Kontrakt, `AgentResult.as_dict()` i capabilities 1:1 z planem (bogatsze: `verified/partial/unsupported/unverified`). **Tylko 1 adapter: Codex CLI (process)** — klasy HTTP/API/service z §6.5 niezaimplementowane |
| §7 Runtime/Router, tryby, modele | ✅ | `direct/runtime/router`, `managed`+`external` (external plan przewidywał „później” — jest od razu), rozdział model vs `routed_model` |
| §8 Dataset, kategorie, trudność, mutacje, hidden tests | ✅ z nadwyżką | 9 kategorii (plan MVP: 2, docelowo: 9), trudności easy–expert, 35 zadań na `f7da55b` (20 bug_fix + 15 new_feature; 22 na `125535b`), mutacje weryfikowane (`--verify-mutations`), hidden tests poza workspace |
| §9 Deskryptory (10 rodzajów) | ⚠️ | 8 kindów w rejestrze + Task + Experiment poza nim. **Brak Environment Descriptor** jako kind (jest `ObservedEnv` w pluginach) |
| §10 Plugin Descriptor i ENV | ✅ | Allowlist `observed_env` z flagami `observed/dimension/controllable/sensitive`, sekrety jako `is_set`, triada + `value_source`, Plugin Adapter |
| §11 Dimension Descriptor | ✅ | Wszystkie 9 typów z §11, gating controllability w plannerze |
| §12 Experiment Descriptor, walidacja, strategie, warianty | ✅ | Walidacja §12.1, 5 strategii (§12.2), stabilne ID + hash + snapshoty (§12.3) |
| §13 Router Manager | ✅ | Triada `requested/effective/observed` + `verification_status` |
| §14 Izolacja i Workspace | ⚠️ | Worktree per run, izolacja pamięciowa, manifest z polami §14 — ✅. **Brak izolacji Docker**; `sandbox_image` w manifeście zawsze `unknown` (uczciwie, nie zgadywane) |
| §15 Lifecycle | ✅ | Stany i przejścia 1:1, brak retry błędów agenta, retry infra konfigurowalny |
| §16 Evaluator Engine | ⚠️ | Patrz Faza 6: pytest + command ✅; verdicts `passed/partial/failed/regression/timeout/evaluator_error/infrastructure_error` ✅; **diff/static/custom-Python bez implementacji** |
| §17 Knowledge Learning/Replay | ✅ | Learning/Replay/Fresh, fingerprint równości par, readiness gate, scenariusze exact/related/negative |
| §18 Metryki | ✅ z zastrzeżeniem | 5 grup, formuły `delta_success/speedup/token_saving` z obsługą baseline=0. **Wszystkie 8 metryk knowledge z §18.4 zadeklarowanych jako `unavailable`** — router nie eksportuje sygnałów; poprawnie nie raportowane jako 0 |
| §19 Storage | ✅ | Wszystkie tabele z §19 + 3 dodatkowe; artefakty z checksum/rozmiarem/powiązaniem z runem |
| §20 Reporting | ✅ | Drzewo `index/experiments/tasks/agents/runtimes/plugins/models` + dodatki (warianty, runy, kategorie, trudności, verdicts, docs); dashboard z §20; tabela „Not verified” — nieudane runy nie są ukrywane |
| §21 Export | ✅ | JSON/CSV/HTML, redakcja sekretów (`export/redact.py`). Brak flag wyłączania promptów/diffów z §21 (redakcja jest automatyczna, nie konfigurowalna) |
| §22 CLI | ⚠️ | Prawie wszystko; rozjazdy w §3 poniżej |
| §23 Bezpieczeństwo i validity | ✅ | `valid/valid_with_warnings/invalid/incomplete`, sekrety, hidden tests, manifesty. Ograniczenie sieci/filesystemu tylko przez `sandbox_mode` Codexa, nie przez AK-Bench |
| §24 Testy | ⚠️→✅ | Unit/contract/integration/E2E/reproducibility istnieją; 18 błędów z `125535b` nie powtarzają się na `f7da55b` (patrz §4, aktualizacja) |
| §25 Eksperymenty startowe A–F | ⚠️ | B ✅, D ✅, F ✅, C częściowo (alias `auto_codex` w macierzach, brak dedykowanego on/off), **A: typ `agent_comparison` istnieje, ale z 1 agentem nie da się go uruchomić**, **E: shipped `full-matrix` to Knowledge×Model (custom), oś Auto Codex świadomie pominięta** (komentarz w YAML) |
| §27 MVP | ✅ z 2 wyjątkami | Docker ❌, SQLite jako domyślna baza ❌ (Postgres). Reszta ✅ |
| §28 Dokumentacja | ⚠️ | 18 plików zamiast 23; brak 11 nazw z listy (treść częściowo scalona w `DATASETS.md`, `EXPERIMENTS.md`, `PLUGINS.md`, `RUNTIME_MANAGER.md`) |
| §29 Instrukcje dla implementatora | ✅ | W praktyce przestrzegane (brak fikcyjnych endpointów/ENV, `unsupported` zamiast atrap) |
| §30 Rezultat końcowy (12 punktów) | ✅ z wyjątkami | Punkty 2/10 ograniczone do 1 agenta; brak resume/cancel |

## 3. Braki i odstępstwa (pełna lista)

1. **Izolacja Docker (§5, §14, §27)** — niezaimplementowana. Izolacja to: git worktree per run + kopia workspace do sandboxa ewaluacyjnego (`evaluators/isolation.py`) + `CODEX_HOME` per run + `sandbox_mode` Codexa. Docker występuje tylko jako opcjonalny tool w `doctor` i ewentualny `command` w deskryptorze runtime.
2. **Evaluatory bez implementacji (§16)** — `diff_evaluator`, `static_analysis_evaluator` mają deskryptory, ale `default_registry()` rejestruje tylko `pytest`+`command` i jawnie rzuca `EvaluatorNotFound` dla pozostałych. Custom Python evaluator: możliwy przez wstrzyknięcie `extra` do rejestru, brak gotowego pliku.
3. **Scheduler (§15, §22)** — brak `experiment resume/cancel`, brak równoległości: pole `concurrency` w YAML jest ignorowane, runy idą sekwencyjnie. `cli/main.py` dokumentuje to jako „intentionally absent rather than stubbed”.
4. **CLI — rozjazdy z §22**: brak `runtime start/stop/verify` (jest `list/health/models/config/state`; managed start jest per-run), brak `experiment show` (jest `history show`), `report` ma składnię `report all/experiment/task` zamiast `report --experiment/--all`. Podsumowanie przed runem (liczby zadań/wariantów/runów) jest ✅.
5. **Drugi agent (§6.5, §25A)** — framework gotowy (dodanie agenta = deskryptor + adapter + testy kontraktowe), ale shipped tylko `codex`. Klasy HTTP/API/service nie istnieją.
6. **Environment Descriptor (§9)** — brak jako osobny kind; środowisko opisane jest przez `observed_env` pluginów i `config/models.py`.
7. **Dokumentacja (§28)** — brak plików: `ARCHITECTURE.md`, `RUNTIME_ADAPTERS.md`, `TASK_FORMAT.md`, `CATEGORY_SYSTEM.md`, `EXPERIMENT_DESCRIPTORS.md`, `DIMENSION_DESCRIPTORS.md`, `EXPERIMENT_TYPES.md`, `FACTORIAL_DESIGN.md`, `ISOLATION_AND_SECURITY.md` (+ `AGENT_ADAPTERS`/`ROUTER_INTEGRATION` istnieją). Ich treść jest w większości pokryta przez `DATASETS.md`, `EXPERIMENTS.md`, `PLUGINS.md`, `RUNTIME_MANAGER.md`, `RUN_ORCHESTRATOR.md`.
8. **Metryki knowledge (§18.4)** — zadeklarowane, ale wszystkie `unavailable` (brak sygnałów po stronie routera). To zgodne z zasadą planu „nie zgaduj”, ale oznacza, że retrieval vs wykorzystanie wiedzy nie są dziś mierzone liczbowo.
9. **Pełna macierz E (§25)** — plan: Knowledge×AutoCodex×Model A/B/C = 12; shipped: Knowledge×Model (2 modele) jako `custom_matrix`. Oś Auto Codex pominięta świadomie (alias to decyzja per-request, nie wartość czynnika).
10. **Odstępstwa pozytywne (ponad plan)**: PostgreSQL jako domyślna baza + migracja SQLite→PG; `bench_ui/` — FastAPI dashboard (plan §5 mówił „nie budować SPA na początku” — CLI i statyczny HTML nadal są podstawą, UI jest dodatkiem); `external` runtime od razu; 9 kategorii zamiast 2; 22 zadania zamiast przykładowych.

## 4. Defekty wykryte testami na świeżym klonie

Uruchomiono: `pytest tests/unit tests/contract tests/integration tests/e2e` (SQLite).
Wynik na `125535b`: **~775 testów, 18 błędów** (1 unit + 17 integration). Przyczyny:

> **Aktualizacja 2026-11-11:** na bieżącym HEAD (`f7da55b`) `tests/unit tests/contract`
> przechodzi **619 testów, 0 błędów, 4 skipy** (markery `live`/`postgres`). Defekt 1
> naprawiony w `6102769` (usuwanie `parts/` z `.gitignore` + commit parts). Defekty 3 i 4
> nie istnieją: test z defektu 3 jest poprawnie napisany, test z defektu 4 nie wymaga
> żywego routera (stub `codex_stub.py`). Defekt 2 (symlink `data`) naprawiony w Fazie A2
> planu do 100%.

| # | Błąd | Przyczyna | Klasyfikacja |
|---|---|---|---|
| 1 | 13 testów: `can't open patch '.../mutations/parts/*.patch'` (atlas-drift-001, depweaver-backtracking-001) | `.gitignore` zawiera generyczny wpis `parts/` (szablon Pythona), który ignoruje `datasets/**/mutations/parts/*.patch` — pliki nigdy nie zostały zcommitowane, mimo że `parts.json` je referencjonuje | **defekt repo** |
| 2 | 2 testy workspaces + `test_dataset_validate_verifies_mutation`: `FileExistsError: '.../data'` | `data` to commitowany symlink → `../ak-bench-data` (osobne repo, nieklonowane); dangling symlink wywala `mkdir(exist_ok=True)` | **defekt repo** (świeży klon bez sibling repo) |
| 3 | `test_the_shipped_atlas_memory_experiment_declares_its_six_arms`: `KeyError: 'LLM_ROUTER_UTILS_PLUGINS_PIPELINE'` | Test zakłada pipeline w `runtime_env` każdego wariantu, ale ramiona `knowledge_enabled: false` celowo go nie mają (brak pluginu w procesie) | **defekt testu** |
| 4 | `test_agent_run_reports_the_execution_plan`: brak `LLM_ROUTER_API_KEY` | Test wymaga żywego routera, nie jest oznaczony `live`/skip | defekt testu (env) |

Poza tymi 18 błędami cała reszta (unit, contract, E2E YAML→HTML, reproducibility) przechodzi.

## 5. Podsumowanie

- **Zrealizowane w pełni:** spike, szkielet, deskryptory, dataset/workspaces, adapter Codexa,
  runtime (managed+external), planner (5 strategii), pluginy/ENV, knowledge replay,
  storage, metryki (poza knowledge), reporting, export, lifecycle, bezpieczeństwo.
- **Zrealizowane częściowo:** evaluatory (2/5), CLI (brak resume/cancel/show/start),
  dokumentacja (18/23 plików), przykłady A/C/E, testy (18 błędów klonowych).
- **Niezrealizowane:** izolacja Docker, scheduler/równoległość, drugi agent,
  Environment Descriptor, mierzenie metryk knowledge.
- **Do naprawy w pierwszej kolejności:** `.gitignore` (`parts/`) — naprawione w `6102769`;
  symlink `data` — naprawiony w Fazie A2 (2026-11-11); test atlasu — nie istniał w tej
  postaci (patrz §4, aktualizacja). Zielony CI na świeżym klonie: osiągnięty.
