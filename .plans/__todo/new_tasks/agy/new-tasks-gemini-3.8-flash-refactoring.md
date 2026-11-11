# Plan implementacji zadań: Kategoria `refactoring`

> **Kategoria:** `refactoring` (Restrukturyzacja kodu z zachowaniem 100% zachowania zewnętrznego)  
> **Deskryptor kategorii:** `descriptors/categories/refactoring.yaml`  
> **Dozwolone poziomy trudności:** `easy`, `medium`, `hard`  
> **Ewaluatory:** `pytest_evaluator`, `command_evaluator`

---

## 1. Przegląd zadań w kategorii `refactoring`

| ID Zadania | Poziom | Ziarno (`_sources`) | Cel refaktoryzacji | Warunek zachowania zachowania (Golden Check) |
| :--- | :---: | :--- | :--- | :--- |
| **`tidewater-state-machine-pattern-001`** | `hard` | `tidewater` | Dekompozycja monolitycznego `Node` do wzorca State Pattern (`FollowerRole`, `LeaderRole` itd.) | Byte-for-byte identyczność sum kontrolnych `traces/*.digest` na 12 harmonogramach |
| **`depweaver-sat-engine-modularization-001`** | `hard` | `depweaver` | Podział monolitycznego solvera CDCL na `TrailWatcher`, `ClauseLearner` i `BackjumpController` | Identyczna kolejność ewaluacji VSIDS i identyczny wynik lockfile |

---

## 2. Zadanie 1: `tidewater-state-machine-pattern-001`

### 2.1 Metadane i kontekst
* **ID:** `tidewater-state-machine-pattern-001`
* **Trudność:** `hard`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/refactoring/tidewater-state-machine-pattern-001/`
* **Ziarno:** `datasets/_sources/tidewater`
* **Ewaluator:** `pytest_evaluator` + `command_evaluator`

### 2.2 Opis problemu i zakres refaktoryzacji
Klasa `Node` w `src/tidewater/node.py` liczy niemal 650 linii kodu i zawiera skomplikowane rozgałęzienia logiczne zależne od aktualnej roli (`self.role == FOLLOWER / PRE_CANDIDATE / CANDIDATE / LEADER`). Prowadzi to do powielania obsługi wspólnych komunikatów (np. `AppendEntries` od wyższego termu zrzucający każdą rolę do `FOLLOWER`).

Zadaniem agenta jest:
1. Wprowadzenie hierarchii klas ról w nowym module `src/tidewater/roles/`:
   * `BaseRole`: wspólne zachowania (odrzucanie starych termów, step-down przy wyższym termie, obsługa heartbeatów).
   * `FollowerRole`: obsługa timeoutów elekcyjnych, przyjmowanie wpisów replikacji.
   * `PreCandidateRole`: zliczanie głosów pre-vote bez modyfikacji termu w storage.
   * `CandidateRole`: formalne wybory, inkrementacja termu, głosowanie na siebie.
   * `LeaderRole`: okresowe heartbeaty, rozsyłanie `AppendEntries`, zarządzanie `match_index` i `next_index`.
2. Klasa `Node` staje się lekkim kontekstem (Context w State Pattern), delegującym `receive()`, `tick()` i `propose()` do aktywnego obiektu roli.
3. Zachowanie absolutnego determinizmu: żaden komunikat w kolejce outbox nie może zmienić swojej kolejności ani o jeden krok.

### 2.3 Dlaczego zadanie jest trudne
Raft ma subtelne reguły przejść stanów – np. przy zrzuceniu roli lidera do followera z powodu wyższego termu, węzeł musi najpierw zapisać stan w `storage.save_state()`, a dopiero potem obsłużyć treść pakietu. Jeśli podział na klasy ról naruszy kolejność tych mikro-kroków, `tools/reference_traces.py --check` natychmiast zgłosi `MISMATCH`.

### 2.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`playbook`:** Agent musi regularnie weryfikować poprawność śladów referencyjnych: `python tools/reference_traces.py --check`.
* **`deadend`:** Zmiana formatu wewnętrznych zdarzeń `Trace` (np. inna nazwa roli w logu) powoduje błąd digestu. Po nieudanej próbie baza wiedzy rejestruje to jako zakaz zmiany nazw ról.
* **`session_archive`:** Refaktoryzacja wymaga przenoszenia fragmentów kodu w wielu krokach, co generuje długą sesję i wywołuje procedurę kompaktowania kontekstu.

### 2.5 Struktura katalogu i ewaluacja
```
datasets/refactoring/tidewater-state-machine-pattern-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_refactored_node_public.py
└── hidden_tests/
    ├── test_trace_byte_compatibility.py
    └── test_role_hierarchy_structure.py
```
* **Kryterium sukcesu:**
  1. `test_role_hierarchy_structure.py`: potwierdzenie dekompozycji (klasa `Node` $< 250$ linii, wydzielone klasy ról).
  2. `test_trace_byte_compatibility.py`: 100% zgodności sum kontrolnych śladów dla wszystkich 12 harmonogramów.

---

## 3. Zadanie 2: `depweaver-sat-engine-modularization-001`

### 3.1 Metadane i kontekst
* **ID:** `depweaver-sat-engine-modularization-001`
* **Trudność:** `hard`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/refactoring/depweaver-sat-engine-modularization-001/`
* **Ziarno:** `datasets/_sources/depweaver`
* **Ewaluator:** `pytest_evaluator`

### 3.2 Opis problemu i zakres refaktoryzacji
W silniku `depweaver` rozwiązywanie zależności bazuje na algorytmie CDCL (Conflict-Driven Clause Learning). Obecnie logika stosu przypisań (trail), mechanizm 2-watched literals oraz uczenie klauzul konfliktowych znajdują się w jednym wielkim pliku `src/depweaver/solver.py`.

Zadaniem agenta jest rozbicie modułu na 3 spójne komponenty:
1. `TrailManager`: zarządzanie poziomami decyzyjnymi, przypisaniami zmiennych i cofaniem stosu (unwinding).
2. `WatcherEngine`: struktura 2-watched literals i propagacja jednostkowa (unit propagation / BCP).
3. `ConflictAnalyzer`: analiza grafu implikacji (First UIP) i minimalizacja wyuczonej klauzuli.

### 3.3 Dlaczego zadanie jest trudne
Heurystyki SAT (kolejność wyboru zmiennych VSIDS, rozstrzyganie remisów) są niezwykle wrażliwe na drobne zmiany w strukturach danych. Jakakolwiek zmiana kolejności iteracji po watched clauses zmienia ścieżkę poszukiwania rozwiązania i generuje inny lockfile.

### 3.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`recipe`:** Prawidłowe zachowanie kolejności w słownikach klauzul staje się receptą wielokrotnego użytku w kolejnych zadaniach depweavera.
* **`doc_context`:** Iniekcja `docs/sat-solver-architecture.md` oraz specyfikacji wyznaczania 1UIP.
* **`deadend`:** Zastąpienie listy watched literals zbiorem `set()` prowadzi do utraty determinizmu (baza odnotowuje zakaz używania struktur nieuporządkowanych).

### 3.5 Struktura katalogu i ewaluacja
```
datasets/refactoring/depweaver-sat-engine-modularization-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_solver_modular_public.py
└── hidden_tests/
    ├── test_lockfile_deterministic_match.py
    └── test_modular_ast_boundaries.py
```
* **Kryterium sukcesu:**
  1. Wszystkie testy jednostkowe `pytest tests/` przechodzą w 100%.
  2. Test `test_lockfile_deterministic_match.py` generuje identyczne lockfile dla 20 złożonych grafów zależności.

---

## 4. Plan wdrożenia i weryfikacji

1. Aktywacja kategorii w `descriptors/categories/refactoring.yaml` (`category.enabled: true`).
2. Przygotowanie testów czystości strukturalnej AST w `hidden_tests/`.
3. Weryfikacja CLI: `.venv/bin/akbench dataset validate --task tidewater-state-machine-pattern-001`.
