# AK-Bench --- kompletny plan implementacji

## 1. Cel projektu

Zbuduj **AK-Bench (Agent Knowledge Benchmark)** --- rozszerzalną
platformę do powtarzalnej oceny agentów AI, LLM Routerów, modeli oraz
pluginów rozszerzających ich możliwości.

AK-Bench ma być narzędziem badawczo-testowym uruchamianym początkowo
lokalnie. Ma umożliwiać wykonywanie zadań na rzeczywistych
repozytoriach, kontrolowanie konfiguracji, izolowanie sesji i środowisk,
mierzenie jakości oraz kosztu, a następnie generowanie raportów HTML i
eksportów danych.

**Najważniejsza zasada architektoniczna: testowany agent jest wymiennym
komponentem.** Pierwszym adapterem będzie Codex, ale AK-Bench nie może
być zbudowany jako benchmark Codexa. W przyszłości powinien obsługiwać
innych agentów CLI, agentów API, agentów uruchamianych przez router oraz
własne implementacje adapterów. Silnik benchmarku nie może zakładać
konkretnego interfejsu, formatu sesji, sposobu przekazywania promptu ani
formatu trace'ów jednego agenta.

AK-Bench nie implementuje własnego agenta, pamięci ani routingu.
Orkiestruje wykonanie zadań przez wybranego agenta lub system agentowy,
np. agenta uruchamianego przez LLM Router.

## 2. Zasady architektoniczne

1.  Agent, router, model, plugin, evaluator i kategoria zadania są
    niezależnymi, wymiennymi komponentami.
2.  Integracja z konkretnym agentem odbywa się przez `Agent Adapter` i
    `Agent Descriptor`.
3.  Logika eksperymentów nie może zależeć od Codexa ani od konkretnego
    sposobu uruchamiania agenta.
4.  Agent może działać bezpośrednio albo za pośrednictwem routera.
    Router jest opcjonalną warstwą wykonawczą, nie częścią definicji
    agenta.
5.  Wszystkie komponenty i deskryptory są wersjonowane.
6.  Każdy run ma izolowany workspace i niezależny kontekst wykonania, o
    ile możliwości badanego agenta na to pozwalają.
7.  Rejestrowane są konfiguracja żądana, efektywna i zaobserwowana.
8.  Konfiguracja nie jest uznawana za aktywną bez weryfikacji.
9.  Nieznane możliwości komponentu są oznaczane jako `unsupported` lub
    `unverified`, a nie symulowane.
10. Wyniki muszą być odtwarzalne na poziomie warunków eksperymentu,
    wersji, snapshotów i konfiguracji.
11. Błędy infrastruktury muszą być odróżnione od błędów agenta.
12. Kategorie, pluginy, metryki i wymiary eksperymentów są rozszerzalne
    przez deskryptory i adaptery.

## 3. Architektura wysokiego poziomu

``` text
                         AK-BENCH
                             |
       +---------------------+----------------------+
       |                     |                      |
  Dataset Manager      Experiment Manager      Reporting
       |                     |                      |
       |               Experiment Planner           |
       |                     |                      |
       +--------------- Run Scheduler --------------+
                             |
                       Run Orchestrator
                             |
             +---------------+----------------+
             |                                |
       Agent Adapter                    Workspace Manager
             |                                |
      Tested Agent                         Git Worktree
             |
       Optional Runtime
             |
       +-----+-------------------------+
       |                               |
  Direct execution                 LLM Router
                                       |
                               Router Plugin System
                                       |
                         Knowledge / Routing / Optimization
             |
       Observability Adapters
             |
      Metrics / Events / Traces
             |
         Evaluator
             |
         Result Store
             |
       HTML / JSON / CSV
```

### 3.1. Rozdzielenie agentów, routerów i modeli

Należy rozróżnić trzy pojęcia:

-   **Agent** --- testowany system wykonujący zadanie. Przykłady: Codex,
    inny agent CLI, agent API, agent własny.
-   **Runtime / Router** --- opcjonalna warstwa pośrednicząca w
    uruchamianiu agenta, dostarczaniu narzędzi, routingu lub pluginów.
    Przykładem jest LLM Router.
-   **Model** --- model lub modele wykorzystywane przez agenta albo
    router. Agent może używać jednego modelu, wielu modeli lub
    dynamicznego routingu.

Nie zakładać, że każdy agent ma jawnie konfigurowalny model. Niektóre
agenty mogą zarządzać wyborem modelu samodzielnie. W takim przypadku
należy rejestrować model tylko wtedy, gdy dostępne są wiarygodne dane.

### 3.2. Główne moduły

  Moduł                          Odpowiedzialność
  ------------------------------ --------------------------------------------
  Dataset Manager                Zadania, wersje datasetów i metadane
  Category Registry              Rozszerzalne kategorie zadań
  Repository Manager             Repozytoria, commity i snapshoty
  Mutation Engine                Kontrolowane mutacje repozytoriów
  Experiment Manager             Definicje i lifecycle eksperymentów
  Experiment Planner             Generowanie wariantów i planu runów
  Agent Registry                 Odkrywanie i rejestracja agentów
  Agent Adapter                  Uniwersalny kontrakt komunikacji z agentem
  Runtime Manager                Opcjonalne zarządzanie routerem/runtime
  Plugin Registry                Deskryptory i adaptery pluginów
  Workspace Manager              Izolacja repozytoriów i środowisk
  Run Orchestrator               Lifecycle pojedynczego runu
  Evaluator Engine               Niezależna ocena wyniku
  Knowledge Experiment Manager   Learning, replay i fresh control
  Observability                  Zdarzenia, trace'y i metryki
  Result Store                   Trwałe zapisywanie danych
  Reporting Engine               Raporty HTML
  Export Manager                 JSON, CSV i HTML

## 4. Etap 0 --- integracyjny spike

Przed implementacją właściwą sprawdzić rzeczywiste możliwości integracji
z pierwszym agentem --- Codexem --- oraz z LLM Routerem, jeśli będzie
używany.

Nie zakładać endpointów, flag CLI, nazw ENV ani formatów zdarzeń bez
potwierdzenia w dokumentacji lub kodzie.

### 4.1. Spike agenta

Sprawdzić i udokumentować:

-   sposób uruchamiania agenta;
-   sposób przekazywania zadania/instrukcji;
-   sposób wskazywania workspace;
-   sposób ustawiania parametrów;
-   sposób rozpoczynania i kończenia sesji;
-   możliwość wymuszenia nowej sesji;
-   możliwość odczytu statusu;
-   sposób wykrywania zakończenia;
-   sposób obsługi timeoutu i anulowania;
-   dostępność token usage i kosztu;
-   dostępność tool calls i trace'ów;
-   możliwość ograniczenia dostępu do plików i sieci;
-   sposób uzyskiwania końcowego wyniku.

Przygotować `docs/AGENT_INTEGRATION.md` z potwierdzonymi informacjami i
ograniczeniami.

### 4.2. Spike routera

Sprawdzić:

-   uruchamianie i zatrzymywanie routera;
-   konfigurację modeli i pluginów;
-   odczyt konfiguracji efektywnej;
-   uruchamianie nowych sesji;
-   logi i trace'y;
-   identyfikację użytych modeli;
-   healthcheck;
-   sygnały aktywności pluginów;
-   mechanizm zapisu i indeksowania wiedzy.

Przygotować `docs/ROUTER_INTEGRATION.md`.

### 4.3. Test end-to-end

Zbudować mały prototyp, który uruchamia Codexa przez wybrany runtime,
przekazuje proste zadanie repozytoryjne, odbiera wynik, zapisuje logi i
końcowy diff oraz poprawnie kończy procesy.

### 4.4. Kryterium ukończenia

Integracja ma być potwierdzona działającym prototypem. Wszystkie
niepotwierdzone możliwości muszą być jawnie opisane. Nie wolno
implementować fikcyjnych endpointów ani pozornej obsługi funkcji.

## 5. Szkielet projektu i technologie

Proponowany stos:

  Obszar         Technologia
  -------------- ---------------
  Język          Python 3.12+
  Walidacja      Pydantic
  Konfiguracja   YAML
  CLI            Typer
  Baza           SQLite
  ORM            SQLAlchemy
  Migracje       Alembic
  Testy          pytest
  Repozytoria    Git worktrees
  Izolacja       Docker
  Raporty        Jinja2
  Wykresy        Chart.js
  Dane surowe    JSON / JSONL

Nie budować na początku wieloużytkownikowego SaaS ani rozbudowanego
frontendowego SPA. Podstawowym interfejsem ma być CLI, a raporty mają
być statycznymi stronami HTML.

### 5.1. Proponowana struktura katalogów

``` text
ak-bench/
├── pyproject.toml
├── README.md
├── configs/
│   ├── defaults.yaml
│   └── experiments/
├── datasets/
├── descriptors/
│   ├── agents/
│   ├── runtimes/
│   ├── routers/
│   ├── plugins/
│   ├── models/
│   ├── evaluators/
│   ├── categories/
│   ├── dimensions/
│   └── metrics/
├── src/akbench/
│   ├── cli/
│   ├── core/
│   ├── config/
│   ├── dataset/
│   ├── categories/
│   ├── repositories/
│   ├── mutations/
│   ├── descriptors/
│   ├── discovery/
│   ├── agents/
│   │   ├── registry.py
│   │   ├── descriptor.py
│   │   ├── adapter.py
│   │   └── adapters/
│   ├── runtimes/
│   ├── router/
│   ├── plugins/
│   ├── dimensions/
│   ├── experiments/
│   ├── sandbox/
│   ├── runner/
│   ├── evaluation/
│   ├── knowledge/
│   ├── observability/
│   ├── metrics/
│   ├── storage/
│   ├── reporting/
│   └── export/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── docs/
├── data/
│   ├── akbench.sqlite
│   ├── artifacts/
│   ├── workspaces/
│   └── runtime_instances/
└── reports/
```

## 6. System agentów --- najważniejszy kontrakt rozszerzalności

### 6.1. Agent Registry

Agent Registry rejestruje dostępne typy agentów na podstawie
deskryptorów i adapterów.

Pierwszym wpisem będzie `codex`, ale nazwa Codex nie może pojawiać się w
logice ogólnego runnera, schedulera, evaluatora ani Experiment Managera.

Dodanie nowego agenta powinno wymagać:

1.  dodania jego Agent Descriptor;
2.  implementacji lub konfiguracji odpowiedniego adaptera;
3.  opcjonalnego adaptera observability;
4.  testów kontraktowych;
5.  rejestracji agenta.

Nie powinno wymagać zmian w logice eksperymentów.

### 6.2. Agent Adapter

Agent Adapter jest warstwą tłumaczącą uniwersalny interfejs AK-Bench na
konkretny interfejs badanego agenta.

Przykładowy kontrakt:

``` python
from typing import Protocol

class AgentAdapter(Protocol):
    def validate_environment(self, config): ...
    def start_session(self, config, workspace): ...
    def submit_task(self, session, task): ...
    def wait_for_completion(self, session, timeout): ...
    def get_status(self, session): ...
    def collect_observations(self, session): ...
    def cancel(self, session): ...
    def close_session(self, session): ...
```

Kontrakt należy dopasować do rzeczywistych możliwości integracyjnych.
Nie każdy agent musi implementować wszystkie funkcje. Brak możliwości
powinien być deklarowany jako capability `unsupported`, a nie
zastępowany atrapą.

### 6.3. Uniwersalny wynik agenta

Adapter powinien normalizować rezultat do wspólnego modelu:

``` json
{
  "agent_id": "codex",
  "agent_version": "detected-or-configured-version",
  "session_id": "session-123",
  "status": "completed",
  "started_at": "ISO-8601",
  "finished_at": "ISO-8601",
  "final_message": null,
  "exit_code": null,
  "workspace_changes": [],
  "observations": {},
  "artifacts": []
}
```

Pola niedostępne pozostają `null` lub otrzymują status `unavailable`.
Nie należy zgadywać wartości.

### 6.4. Capability model

Każdy agent deklaruje możliwości, np.:

-   `workspace_binding`;
-   `fresh_session`;
-   `session_reset`;
-   `task_submission`;
-   `completion_detection`;
-   `cancellation`;
-   `token_usage`;
-   `cost_usage`;
-   `tool_trace`;
-   `model_observation`;
-   `streaming_output`;
-   `network_control`;
-   `filesystem_control`;
-   `session_export`.

Możliwości powinny być opisane w deskryptorze i potwierdzane przez
adapter, jeśli to możliwe.

Eksperyment może wymagać konkretnych capabilities. Planner ma odrzucić
plan, jeżeli agent ich nie zapewnia, albo oznaczyć ograniczenie, jeśli
użytkownik jawnie dopuści tryb best-effort.

### 6.5. Różne klasy agentów

Architektura powinna umożliwiać obsługę:

-   agentów CLI uruchamianych jako proces;
-   agentów dostępnych przez HTTP/API;
-   agentów działających jako usługa;
-   agentów uruchamianych przez router;
-   agentów z własnym runtime i narzędziami;
-   agentów wielomodelowych.

Nie należy zakładać, że każdy agent ma pojęcie sesji w takim samym
znaczeniu. Adapter mapuje pojęcia konkretnego systemu na model AK-Bench.

### 6.6. Agent Descriptor

Przykład:

``` yaml
schema_version: "1.0"
id: codex
version: "1.0.0"
title: Codex
description: Codex agent adapter configuration.

agent:
  adapter: codex_cli
  execution_type: process

  capabilities:
    workspace_binding: true
    fresh_session: true
    cancellation: true
    token_usage: true
    cost_usage: false
    tool_trace: true
    model_observation: true

  configuration_schema:
    model:
      type: string
      controllable: true
    reasoning_effort:
      type: string
      controllable: true

  observability:
    session_id: supported
    token_usage: supported
    tool_calls: supported
    model_selection: supported
```

To przykładowy format AK-Bench. Faktyczne parametry i capabilities muszą
być zgodne z integracją danego agenta.

### 6.7. Konfiguracja agenta

Eksperyment wskazuje agenta i jego konfigurację, ale nie może zakładać,
że każdy agent obsługuje identyczne parametry.

Przykładowo:

``` yaml
agent:
  id: codex
  version: "1.0.0"

  config:
    model: model-a
    reasoning_effort: medium
```

Dla innego agenta może to wyglądać inaczej. Walidacja odbywa się według
Agent Descriptor i schematu adaptera.

### 6.8. Testy kontraktowe adapterów

Każdy adapter musi przejść wspólny zestaw testów:

-   walidacja konfiguracji;
-   uruchomienie;
-   wskazanie workspace;
-   przekazanie zadania;
-   wykrycie zakończenia;
-   timeout;
-   anulowanie;
-   zamknięcie sesji;
-   normalizacja statusu;
-   zebranie dostępnych obserwacji;
-   obsługa niedostępnych metryk.

Dodanie nowego agenta wymaga przejścia testów kontraktowych, zanim
będzie mógł być używany w eksperymentach oznaczonych jako `valid`.

## 7. Runtime i Router Manager

Agent i router muszą być odrębnymi obiektami. Agent może działać bez
routera.

### 7.1. Tryby wykonania

-   `direct` --- AK-Bench uruchamia agenta bezpośrednio.
-   `runtime` --- agent jest uruchamiany przez pośredni runtime.
-   `router` --- agent lub żądania modelowe przechodzą przez router.

Eksperyment musi jawnie wskazać tryb.

### 7.2. Router Manager

Dla LLM Routera przygotować adapter zarządzający lifecycle:

``` python
class RuntimeManager:
    def start(self): ...
    def stop(self): ...
    def healthcheck(self): ...
    def apply_configuration(self, config): ...
    def read_configuration(self): ...
    def verify_configuration(self, expected): ...
    def collect_runtime_state(self): ...
```

Preferowany początkowy tryb to `managed`, w którym AK-Bench uruchamia
dedykowaną instancję. Tryb `external` można dodać później i wymaga on
weryfikacji konfiguracji oraz ochrony przed zmianami podczas
eksperymentu.

### 7.3. Modele

Nie utożsamiać agenta z modelem. Model może być:

-   konfigurowany bezpośrednio w agencie;
-   konfigurowany w routerze;
-   wybierany dynamicznie;
-   ukryty przed AK-Bench.

Rejestrować model tylko na podstawie wiarygodnych obserwacji. Przy
dynamicznym routingu logować każdy faktycznie użyty model i decyzje
routingu, jeśli są dostępne.

## 8. Dataset, zadania i kategorie

### 8.1. Kategorie

Początkowo:

-   `bug_fix`;
-   `new_feature`.

Docelowo również:

-   `refactoring`;
-   `performance`;
-   `testing`;
-   `security`;
-   `debugging`;
-   `code_review`;
-   `architecture`.

Kategorie nie mogą być zamkniętym enumem w silniku. Mają być
rejestrowane przez Category Descriptor.

### 8.2. Trudność

Poziomy:

-   `easy`;
-   `medium`;
-   `hard`;
-   `expert`.

Trudność jest metadanymi zadania. Nie zmienia automatycznie parametrów
agenta, chyba że eksperyment jawnie tak definiuje.

### 8.3. Task Descriptor

Każde zadanie ma stabilne ID i wersję, repozytorium, commit, opis,
kategorię, trudność, setup, testy, evaluator i ograniczenia.

Przykładowa struktura:

``` text
datasets/
  bug_fix/
    bugfix-001/
      task.yaml
      description.md
      repository.yaml
      public_tests/
      hidden_tests/
      evaluator.yaml
      mutations/
        mutation-001.patch
```

### 8.4. Bug Fix

Poprawne repozytorium jest modyfikowane kontrolowanym, wersjonowanym
patchem. Mutacja musi zostać zweryfikowana testami przed udostępnieniem
zadania agentowi. Nie stosować losowego psucia kodu.

### 8.5. New Feature

Agent otrzymuje repozytorium bazowe i specyfikację funkcjonalności.
Ocena odbywa się przez hidden tests, testy regresyjne i ewentualne
dodatkowe evaluatory.

### 8.6. Hidden tests

Hidden tests i evaluator muszą być poza workspace agenta. Agent nie może
ich odczytać ani modyfikować. Wyniki należy zbierać w izolowanym
środowisku.

## 9. Deskryptory i registry

Wszystkie rozszerzalne komponenty mają deskryptory wersjonowane przez
`schema_version`, `id` i `version`.

Rodzaje:

  Deskryptor               Przeznaczenie
  ------------------------ -------------------------
  Agent Descriptor         Agent i capabilities
  Runtime Descriptor       Runtime lub router
  Plugin Descriptor        Pluginy runtime/routera
  Model Descriptor         Modele i parametry
  Category Descriptor      Kategorie zadań
  Task Descriptor          Zadania
  Evaluator Descriptor     Sposób oceny
  Experiment Descriptor    Definicja eksperymentu
  Dimension Descriptor     Czynnik eksperymentu
  Metric Descriptor        Metryka
  Environment Descriptor   Środowisko wykonawcze

Każdy deskryptor musi być walidowany przez Pydantic, wersjonowany i
zapisywany jako snapshot w eksperymencie. Zmiana deskryptora nie może po
cichu zmieniać interpretacji historycznych wyników.

## 10. Plugin Descriptor i ENV

Plugin Descriptor opisuje tożsamość pluginu, wersję, capabilities,
aktywację, zależności, obserwowalne ENV, metryki i wymiary.

Przykładowy format:

``` yaml
schema_version: "1.0"
id: agentic_knowledge
version: "1.0.0"

plugin:
  provider: llm-router
  type: knowledge
  capabilities:
    - knowledge_read
    - knowledge_write
    - retrieval

benchmark:
  enabled: true

  activation:
    method: router_configuration

  verification:
    required: true
    methods:
      - effective_router_config
      - plugin_runtime_events

  observed_env:
    - name: ACTUAL_ENV_NAME_FROM_PLUGIN
      type: boolean
      role: feature_toggle
      observed: true
      dimension: true
      controllable: true
      sensitive: false

    - name: ACTUAL_CONNECTION_ENV
      type: string
      role: infrastructure
      observed: true
      dimension: false
      controllable: false
      sensitive: true

  metrics:
    - knowledge_retrieval_count
    - knowledge_write_count
    - knowledge_retrieval_latency
```

Nazwy ENV w rzeczywistych deskryptorach muszą pochodzić z dokumentacji
lub kodu pluginu. Nie kopiować przykładowych nazw jako faktów.

### 10.1. Rozdzielenie pól

-   `observed` --- stan ma być obserwowany;
-   `dimension` --- parametr może być czynnikiem eksperymentu;
-   `controllable` --- AK-Bench może bezpiecznie zmienić parametr;
-   `sensitive` --- wartości nie wolno zapisywać.

Nie skanować i nie zapisywać całego środowiska procesu. Obserwować
wyłącznie jawnie wskazane zmienne.

Sekrety mogą być reprezentowane jedynie jako `is_set`, bez zapisywania
treści.

### 10.2. Stan pluginu

Rejestrować oddzielnie:

-   `requested_config`;
-   `configured_value`;
-   `effective_value`;
-   `observed_value`;
-   `verification_status`;
-   `value_source`.

Statusy: `verified`, `unverified`, `mismatch`, `unsupported`,
`not_configured`, `runtime_error`.

Obecność ENV lub wpisu konfiguracyjnego nie jest dowodem działania
pluginu.

### 10.3. Plugin Adapter

Adapter odpowiada za odczyt i zmianę konfiguracji, weryfikację,
interpretację zdarzeń i normalizację metryk. Nie umieszczać obsługi
konkretnego pluginu w głównym silniku eksperymentów.

## 11. Dimension Descriptor

Dimension opisuje parametr eksperymentu. Obsługiwane typy:

-   boolean;
-   categorical;
-   integer;
-   float;
-   string;
-   agent reference;
-   model reference;
-   plugin configuration;
-   runtime configuration.

Deskryptor powinien określać źródło, wartości dozwolone,
controllability, sposób konfiguracji i weryfikacji oraz zależności.

Wymiary niekontrolowalne mogą być obserwowane, ale nie mogą być używane
do generowania wariantów.

## 12. Experiment Descriptor

Eksperyment jest definiowany w wersjonowanym YAML. Musi wskazywać
testowanego agenta, opcjonalny runtime/router, dataset, czynniki,
strategię macierzy, powtórzenia, izolację, evaluatory i metryki.

Przykład:

``` yaml
schema_version: "1.0"
id: knowledge-model-factorial
version: "1.0.0"
title: Knowledge and Model Factorial Experiment

experiment:
  type: configuration

  agent:
    id: codex
    version: "1.0.0"
    config:
      model: model-a

  execution:
    mode: router
    runtime:
      id: llm_router
      lifecycle: managed

  dataset:
    id: software-engineering
    version: "1.0.0"
    filters:
      categories: [bug_fix, new_feature]
      difficulties: [easy, medium, hard]
      task_ids: []

  factors:
    strategy: full_factorial
    dimensions:
      - id: knowledge_enabled
        values: [true, false]
      - id: auto_codex_enabled
        values: [true, false]
      - id: model
        values: [model-a, model-b, model-c]

  execution_policy:
    repetitions: 3
    concurrency: 1
    timeout_seconds: 1800
    retry_infrastructure_errors: 1
    retry_agent_failures: 0

  isolation:
    workspace_per_run: true
    fresh_agent_session: true
    clean_agent_context: true

  evaluation:
    evaluators:
      - pytest_evaluator

  metrics:
    - task_success_rate
    - hidden_test_pass_rate
    - execution_time
    - input_tokens
    - output_tokens
    - total_cost
    - tool_calls

  reporting:
    generate_html: true
    generate_json: true
    generate_csv: true
```

### 12.1. Walidacja

Przed uruchomieniem sprawdzić:

-   istnienie datasetu i wersji;
-   dostępność agenta i adaptera;
-   wymagane capabilities agenta;
-   dostępność runtime, jeśli jest wymagany;
-   istnienie pluginów i wymiarów;
-   controllability wymiarów;
-   dozwolone wartości;
-   kompatybilność parametrów;
-   dostępność evaluatorów i metryk;
-   limity zasobów;
-   sprzeczne ustawienia.

Niepoprawny deskryptor blokuje uruchomienie.

### 12.2. Strategie generowania wariantów

Implementować jako wymienne strategie:

-   `full_factorial`;
-   `selected_factors`;
-   `one_factor_at_a_time`;
-   `pairwise`;
-   `custom_matrix`.

Każdy eksperyment powinien mieć możliwość wskazania baseline.

Planner oblicza liczbę wariantów, zadań, powtórzeń i runów. Przed
uruchomieniem prezentuje kosztowność planu i stosuje konfigurowalne
limity.

### 12.3. Wariant eksperymentu

Każdy wariant przechowuje stabilny ID, wartości wymiarów, konfigurację
żądaną, hash konfiguracji i snapshoty deskryptorów. Każdy run wskazuje
konkretny wariant.

## 13. Router Manager

Router jest opcjonalnym runtime. W pierwszej wersji preferowany jest
tryb `managed`, w którym AK-Bench uruchamia dedykowaną instancję. Tryb
`external` może zostać dodany później.

Nie zmieniać konfiguracji współdzielonego routera w trakcie
eksperymentu. Jeśli nie można potwierdzić stabilności konfiguracji,
eksperyment powinien zostać oznaczony jako niezweryfikowany lub
nieważny.

Zapisywać oddzielnie:

``` json
{
  "requested_config": {},
  "effective_config": {},
  "observed_config": {},
  "verification_status": "verified"
}
```

## 14. Izolacja i Workspace Manager

Każdy run otrzymuje osobny workspace, sesję agenta, identyfikator, logi
i artefakty. W eksperymentach pamięciowych izolować również historię,
cache, pliki lokalne, procesy i przestrzenie danych pluginów.

Używać Git worktrees i kontrolowanych kontenerów Docker. Agent nie może
mieć dostępu do hidden tests, konfiguracji benchmarku ani artefaktów
innych runów.

Każdy run musi mieć Reproducibility Manifest zawierający m.in.:

-   experiment ID i variant ID;
-   agent ID, wersję, adapter i konfigurację;
-   runtime/router ID i wersję, jeśli dotyczy;
-   wersje pluginów i deskryptorów;
-   task ID i wersję;
-   commit i hash repozytorium;
-   hash konfiguracji;
-   obraz sandboxa;
-   parametry wykonania.

## 15. Run Orchestrator i lifecycle

Run Orchestrator nie może znać specyfiki Codexa. Korzysta wyłącznie z
Agent Adapter, opcjonalnego Runtime Manager, Workspace Manager i
Evaluator Engine.

Przykładowy lifecycle:

``` text
PENDING
  -> PREPARING
  -> VALIDATING
  -> CONFIGURING_RUNTIME
  -> CREATING_WORKSPACE
  -> STARTING_AGENT
  -> EXECUTING
  -> COLLECTING
  -> EVALUATING
  -> FINALIZING
  -> COMPLETED
```

Dodatkowe statusy:

-   `FAILED`;
-   `TIMEOUT`;
-   `CANCELLED`;
-   `INFRASTRUCTURE_ERROR`;
-   `INVALID_CONFIGURATION`;
-   `EVALUATION_ERROR`.

Nie ponawiać automatycznie błędów agenta. Retry infrastruktury musi być
jawnie skonfigurowany i rejestrowany.

## 16. Evaluator Engine

Evaluator ocenia rezultat niezależnie od deklaracji agenta. Obsługiwać:

-   pytest;
-   command evaluator;
-   unit/integration tests;
-   static analysis;
-   diff evaluator;
-   custom Python evaluator.

Hidden tests uruchamiać poza workspace agenta. Zachowywać surowe wyniki
testów i wersję evaluatora.

Rozróżniać:

-   pełny sukces;
-   częściowy sukces;
-   porażkę;
-   regresję;
-   timeout;
-   błąd evaluatora;
-   błąd infrastruktury.

## 17. Knowledge Learning / Replay

Główny eksperyment badawczy dotyczący `agentic_knowledge` ma trzy
warianty:

1.  **Learning Run** --- agent wykonuje zadania z aktywnym zapisem i
    odczytem wiedzy.
2.  **Knowledge Replay** --- nowa sesja, czysty workspace, dostęp do
    wiedzy z Learning, bez historii poprzedniej sesji.
3.  **Fresh Control** --- nowa sesja, czysty workspace, bez dostępu do
    wiedzy z Learning.

Replay i Fresh muszą korzystać z identycznego snapshotu repozytorium,
wersji zadania, testów, evaluatora, agenta, parametrów i limitów.

Przed Replay należy potwierdzić zakończenie zapisu i indeksowania
wiedzy. Nie zakładać, że koniec sesji oznacza gotowość KB.

Dodać scenariusze:

-   exact replay --- identyczne zadanie;
-   related transfer --- podobne, ale inne zadanie;
-   negative transfer --- zadanie, w którym wcześniejsza wiedza może być
    myląca.

Retrieval nie jest równoznaczny z wykorzystaniem wiedzy. Mierzyć oba
zjawiska oddzielnie.

## 18. Metrics i Observability

### 18.1. Quality

-   task success rate;
-   hidden test pass rate;
-   partial success;
-   regression rate;
-   evaluator score.

### 18.2. Efficiency

-   całkowity i aktywny czas;
-   input/output/total tokens;
-   koszt;
-   liczba wywołań narzędzi;
-   liczba wywołań modeli.

### 18.3. Agent i runtime

-   agent i wersja;
-   adapter i wersja;
-   session ID;
-   statusy;
-   użyte modele, jeśli obserwowalne;
-   routing i eskalacje, jeśli dostępne;
-   tool calls i trace'y, jeśli dostępne.

### 18.4. Knowledge

-   liczba zapisów;
-   retrieval count;
-   hit rate;
-   retrieval latency;
-   wykorzystanie wiedzy;
-   false positive retrieval;
-   indexing latency;
-   rozmiar KB.

### 18.5. Reliability

-   timeout rate;
-   infrastructure failure rate;
-   agent crash rate;
-   router error rate;
-   incomplete trace rate.

Brak danych zapisuj jako `null` lub `unavailable`. Nie traktuj krótszego
czasu, mniejszej liczby tokenów ani mniejszej liczby tool calls jako
automatycznego sukcesu.

Podstawowe porównania:

``` text
delta_success = success_variant - success_baseline
speedup = time_baseline / time_variant
token_saving = 1 - tokens_variant / tokens_baseline
```

Przy baseline równym zero raportować różnicę bezwzględną.

## 19. Storage

Początkowo SQLite dla metadanych i relacji, JSONL/JSON oraz pliki dla
trace'ów i artefaktów.

Główne tabele:

-   `benchmarks`;
-   `datasets`;
-   `tasks`;
-   `repositories`;
-   `experiments`;
-   `experiment_variants`;
-   `task_runs`;
-   `evaluations`;
-   `metrics`;
-   `artifacts`;
-   `plugin_observations`;
-   `agent_observations`;
-   `model_observations`;
-   `experiment_metrics`;
-   `descriptor_snapshots`;
-   `events`.

Duże trace'y nie powinny być przechowywane bezpośrednio w SQLite.

Przykładowy katalog artefaktów:

``` text
data/artifacts/exp-0001/run-0001/
  metadata.json
  manifest.json
  events.jsonl
  agent_trace.jsonl
  runtime_trace.jsonl
  tool_calls.jsonl
  evaluation.json
  diff.patch
  stdout.log
  stderr.log
  metrics.json
```

Każdy artefakt powinien mieć checksum, rozmiar, typ i powiązanie z
runem.

## 20. Reporting Engine

Generować statyczne raporty HTML:

``` text
reports/
  index.html
  experiments/exp-0001/index.html
  tasks/bugfix-001/index.html
  agents/index.html
  runtimes/index.html
  plugins/index.html
  models/index.html
  assets/
```

Dashboard główny:

-   liczba eksperymentów i runów;
-   skuteczność;
-   wyniki według kategorii i trudności;
-   czas;
-   tokeny;
-   koszt;
-   porównanie agentów;
-   porównanie runtime/routerów;
-   porównanie pluginów;
-   ostatnie eksperymenty.

Raport eksperymentu powinien pokazywać deskryptor, dataset, warianty,
konfiguracje requested/effective/observed, status weryfikacji, wyniki,
metryki, błędy i artefakty.

Raport pojedynczego zadania powinien pokazywać wszystkie runy, agentów,
konfiguracje, testy, diffy, czas, tokeny i koszt.

Raporty nie mogą ukrywać nieudanych runów ani niezweryfikowanych
konfiguracji.

## 21. Export i publikowanie

Pierwsze formaty:

-   HTML;
-   JSON;
-   CSV.

Eksport eksperymentu powinien zawierać deskryptor, snapshoty
deskryptorów, warianty, runy, metryki, manifesty i wybrane artefakty.

Przed publikacją usuwać sekrety, klucze API, prywatne dane i wrażliwe
fragmenty promptów/trace'ów. Umożliwić wyłączenie eksportu pełnych
promptów i diffów.

## 22. CLI

Przykładowe komendy:

``` bash
akbench init
akbench doctor

akbench agent list
akbench agent inspect codex
akbench descriptor list
akbench descriptor validate

akbench dataset list
akbench dataset validate
akbench category list

akbench runtime status
akbench runtime start
akbench runtime verify

akbench experiment validate configs/experiments/example.yaml
akbench experiment plan configs/experiments/example.yaml
akbench experiment run configs/experiments/example.yaml
akbench experiment list
akbench experiment show exp-0001
akbench experiment resume exp-0001
akbench experiment cancel exp-0001

akbench report --experiment exp-0001
akbench report --all
akbench export --experiment exp-0001 --format json
```

Nazwy komend są propozycją CLI i mogą zostać dopasowane podczas
implementacji.

Przed uruchomieniem eksperymentu CLI powinno wyświetlić liczbę zadań,
wariantów, powtórzeń i runów, wskazanego agenta, runtime, wymagane
capabilities oraz status walidacji.

## 23. Bezpieczeństwo i wiarygodność

-   Nie zapisywać sekretów.
-   Nie udostępniać agentowi hidden tests.
-   Nie pozwalać agentowi modyfikować datasetu, evaluatorów ani
    konfiguracji eksperymentu.
-   Izolować workspace i artefakty runów.
-   Ograniczać sieć i filesystem w sandboxie.
-   Zachowywać manifesty i hashe.
-   Nie zmieniać konfiguracji runtime w trakcie runu.
-   Nie uznawać deklaracji agenta za wynik ewaluacji.
-   Nie ukrywać brakujących danych.

Status eksperymentu:

-   `valid`;
-   `valid_with_warnings`;
-   `invalid`;
-   `incomplete`.

Przyczyny nieważności mogą obejmować niezweryfikowaną konfigurację, brak
wymaganych capabilities, brak hidden tests, niepoprawny snapshot,
przeciek danych lub brak gotowości KB.

## 24. Testy

### Unit tests

Walidacja deskryptorów, tasków, kategorii, registry, wymiarów,
generatora wariantów, hashy, ENV allowlist, sekretów, metryk i
serializacji.

### Adapter contract tests

Wspólny zestaw testów dla każdego agenta: konfiguracja, start,
workspace, task submission, completion, timeout, cancel, close,
normalizacja wyniku i obserwacje.

### Integration tests

Router/runtime, agent adapter, plugin adapter, repository manager,
sandbox, evaluator, storage i reporting.

### End-to-end

Mały dataset zawierający bug fix, new feature, timeout, błędną
konfigurację, brak pluginu i błąd evaluatora. Przejść od YAML do raportu
HTML.

### Reproducibility tests

Sprawdzić zgodność snapshotów, konfiguracji, testów, deskryptorów,
identyfikatorów i kompletności artefaktów. Nie wymagać identycznych
odpowiedzi LLM, ale wymagać identycznych warunków eksperymentu.

## 25. Przykładowe eksperymenty startowe

### A. Porównanie agentów

Ten sam dataset, runtime, warunki i evaluator, różni agenci, np. Codex i
kolejny adapter. Porównywać tylko możliwości wspólne lub jawnie oznaczać
różnice capabilities.

### B. Wpływ Knowledge

Knowledge ON/OFF, ten sam agent, model i pozostała konfiguracja.

### C. Wpływ Auto Codex

Auto Codex ON/OFF, z rejestrowaniem faktycznie użytych modeli i decyzji
routingu.

### D. Porównanie modeli

Jeden agent i stała konfiguracja, różne modele, o ile agent/runtime
pozwala jawnie sterować modelem.

### E. Pełna macierz

Knowledge ON/OFF × Auto Codex ON/OFF × Model A/B/C = 12 wariantów.

### F. Knowledge Learning / Replay

Learning, Replay i Fresh Control, z testami exact replay, transfer i
negative transfer.

## 26. Kolejność implementacji

### Faza 0 --- integracyjny spike

Potwierdzenie integracji z Codexem, LLM Routerem i pluginami.
Dokumentacja rzeczywistych możliwości.

**Done:** działający prototyp i `AGENT_INTEGRATION.md` oraz
`ROUTER_INTEGRATION.md`.

### Faza 1 --- szkielet

Struktura, CLI, konfiguracja, logging, SQLite, SQLAlchemy, testy.

**Done:** `akbench doctor`, inicjalizacja i migracje.

### Faza 2 --- deskryptory i registry

Wspólny system deskryptorów, Agent Descriptor, Runtime Descriptor,
Plugin Descriptor, Model Descriptor, Category, Evaluator, Dimension i
Metric Descriptor.

**Done:** można dodać agenta i plugin przez adapter/deskryptor bez zmian
w silniku eksperymentów.

### Faza 3 --- dataset i repozytoria

Task Descriptor, dataset validation, category registry, snapshoty,
worktrees i mutacje.

**Done:** powtarzalne workspace dla zadań.

### Faza 4 --- Agent Adapter Framework

Uniwersalny kontrakt, Agent Registry, capabilities, testy kontraktowe i
pierwszy adapter Codexa.

**Done:** Codex działa przez adapter, a runner nie zawiera kodu
specyficznego dla Codexa.

### Faza 5 --- Runtime Manager

Obsługa direct/runtime/router, pierwszy adapter LLM Routera,
konfiguracja i weryfikacja.

**Done:** zadanie działa z agentem bezpośrednio lub przez zadeklarowany
runtime.

### Faza 6 --- Evaluator Engine

Pytest, command evaluator, hidden tests i wyniki.

**Done:** niezależna ocena wykonania zadania.

### Faza 7 --- Run Orchestrator i Scheduler

Lifecycle, retry, timeout, cancel, resume, izolacja i artefakty.

**Done:** stabilna seria runów.

### Faza 8 --- Experiment Descriptor i Planner

Walidacja, Dimension Registry, strategie macierzy, baseline i szacowanie
skali.

**Done:** plan eksperymentu można wygenerować bez uruchamiania.

### Faza 9 --- Plugin Configuration i Observability

Plugin adapters, ENV allowlist, requested/effective/observed, metryki i
trace'y.

**Done:** weryfikacja pluginów i zbieranie ich dostępnych danych.

### Faza 10 --- Knowledge Replay

Learning, Replay, Fresh, gotowość KB, izolacja i transfer.

**Done:** poprawny eksperyment pamięciowy.

### Faza 11 --- Storage i Metrics

Kompletny model danych, artefakty, hashe, agregacje i statystyki.

**Done:** pełna historia eksperymentów jest zapisana.

### Faza 12 --- Reporting

Dashboard, raport eksperymentu, zadania, agentów, runtime i pluginów.

**Done:** analiza wyników przez statyczny HTML.

### Faza 13 --- Export i stabilizacja

Eksport, filtrowanie sekretów, E2E, dokumentacja i testy powtarzalności.

**Done:** platforma nadaje się do regularnych eksperymentów testowych.

## 27. Zakres MVP

Pierwsza działająca wersja powinna zawierać:

  -----------------------------------------------------------------------
  Obszar                              MVP
  ----------------------------------- -----------------------------------
  Agenci                              Framework adapterów + Codex jako
                                      pierwszy adapter

  Runtime                             Bezpośredni tryb i jeden adapter
                                      LLM Routera

  Kategorie                           bug_fix, new_feature

  Trudności                           easy, medium, hard, expert

  Pluginy                             agentic_knowledge, auto_codex przez
                                      deskryptory/adapters

  Modele                              Konfigurowalne, jeśli wspierane
                                      przez agenta/runtime

  Deskryptory                         agent, runtime, router, plugin,
                                      model, task, experiment, evaluator,
                                      dimension

  Eksperymenty                        configuration, knowledge replay,
                                      agent comparison

  Strategie                           full factorial, custom matrix

  Izolacja                            Git worktree + Docker

  Evaluator                           pytest + command

  Storage                             SQLite + JSONL

  Raporty                             HTML

  Eksport                             JSON, CSV, HTML

  CLI                                 Podstawowe zarządzanie i
                                      uruchamianie
  -----------------------------------------------------------------------

Nie implementować na początku SaaS, kont użytkowników, rozproszonego
schedulera, klastra workerów ani obsługi dziesiątek agentów.
Architektura ma jednak umożliwiać ich późniejsze dodanie.

## 28. Dokumentacja projektu

Utworzyć:

``` text
docs/
  ARCHITECTURE.md
  AGENT_INTEGRATION.md
  ROUTER_INTEGRATION.md
  AGENT_ADAPTERS.md
  RUNTIME_ADAPTERS.md
  DATASET_FORMAT.md
  TASK_FORMAT.md
  CATEGORY_SYSTEM.md
  DESCRIPTOR_SYSTEM.md
  PLUGIN_DESCRIPTORS.md
  EXPERIMENT_DESCRIPTORS.md
  DIMENSION_DESCRIPTORS.md
  EXPERIMENT_TYPES.md
  FACTORIAL_DESIGN.md
  KNOWLEDGE_EXPERIMENTS.md
  EVALUATORS.md
  ISOLATION_AND_SECURITY.md
  METRICS.md
  STORAGE.md
  REPORTING.md
  CLI.md
  DEVELOPMENT.md
  REPRODUCIBILITY.md
```

Dokumentacja ma odzwierciedlać faktyczną implementację. Nie opisywać
funkcji, które nie istnieją.

## 29. Instrukcje dla agenta implementującego

1.  Najpierw przeanalizuj istniejące repozytorium i środowisko.
2.  Rozpocznij od integracyjnego spike'u, nie od budowania całej
    platformy.
3.  Nie zakładaj, że Codex będzie jedynym lub docelowym agentem.
4.  Nie umieszczaj nazw i logiki Codexa w ogólnym runnerze.
5.  Każdy agent musi być obsługiwany przez Agent Descriptor i Agent
    Adapter.
6.  Dodanie nowego agenta ma nie wymagać zmian w Experiment Managerze,
    Schedulerze ani Evaluatorze.
7.  Utrzymuj rozdział agent / runtime / router / model.
8.  Nie zakładaj, że każdy agent obsługuje sesje, tokeny, koszty,
    trace'y lub konfigurowalny model.
9.  Wymagane capabilities waliduj przed eksperymentem.
10. Nie wymyślaj endpointów, flag, nazw ENV ani formatów logów.
11. Obserwuj tylko ENV jawnie wskazane w deskryptorach.
12. Nie zapisuj sekretów.
13. Zapisuj requested, effective i observed configuration osobno.
14. Nie uznawaj konfiguracji za aktywną bez weryfikacji.
15. Nie udostępniaj agentowi hidden tests.
16. Nie mieszaj eksperymentów konfiguracji z eksperymentami uczenia
    pamięci.
17. Nie utożsamiaj retrieval z wykorzystaniem wiedzy.
18. Nie traktuj błędów infrastruktury jako błędów agenta.
19. Nie usuwaj nieudanych runów z raportów.
20. Każdy run musi mieć manifest i identyfikowalne wersje.
21. Każdy deskryptor musi być wersjonowany i walidowany.
22. Implementuj etapami, uruchamiaj testy po każdej fazie i aktualizuj
    dokumentację.
23. Priorytetem jest poprawność metodologiczna i wiarygodność wyników,
    nie liczba funkcji.
24. Nie optymalizuj przedwcześnie pod wielką skalę.
25. Jeśli integracja nie zapewnia danej funkcji, oznacz ją jako
    `unsupported` lub `unverified`; nie twórz pozornej obsługi.

## 30. Końcowy rezultat

Użytkownik powinien móc:

1.  Dodać dataset z zadaniami.
2.  Wybrać dowolnego zarejestrowanego agenta.
3.  Wybrać tryb bezpośredni lub runtime/router, jeśli jest potrzebny.
4.  Skonfigurować dostępne modele i pluginy.
5.  Zdefiniować eksperyment w YAML.
6.  Zweryfikować plan i liczbę runów.
7.  Uruchomić eksperyment.
8.  Obserwować wykonanie i zbierane metryki.
9.  Otrzymać niezależną ocenę każdego zadania.
10. Porównać agentów, modele, runtime'y, pluginy i konfiguracje.
11. Otworzyć raport HTML dla eksperymentu i pojedynczego zadania.
12. Wyeksportować wyniki i artefakty.

**Warunek jakości:** AK-Bench ma mierzyć rzeczywiste działanie
testowanego systemu. Musi jednoznacznie odpowiadać na pytania: jaki
agent został uruchomiony, przez jaki runtime, z jaką konfiguracją, jakie
capabilities były dostępne, co udało się zaobserwować, co agent
faktycznie wykonał i jaki był niezależnie zweryfikowany rezultat.
