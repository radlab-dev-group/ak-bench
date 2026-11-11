# Plan implementacji zadań: Kategoria `architecture`

> **Kategoria:** `architecture` (Przebudowa architektury bazy kodu wg kryteriów akceptacji)  
> **Deskryptor kategorii:** `descriptors/categories/architecture.yaml`  
> **Dozwolone poziomy trudności:** `hard`, `expert`  
> **Ewaluatory:** `pytest_evaluator`, `static_analysis_evaluator`

---

## 1. Przegląd zadań w kategorii `architecture`

| ID Zadania | Poziom | Ziarno (`_sources`) | Cel architektoniczny | Ograniczenia i acceptance criteria |
| :--- | :---: | :--- | :--- | :--- |
| **`atlas-pluggable-storage-engine-001`** | `expert` | `atlas` | Ekstrakcja monolitycznego I/O do interfejsu `StorageEngine` SPI z dwoma silnikami | Zero zależności cyklicznych, zgodność z `tools/check_arch.py`, pełna wsteczna kompatybilność API |
| **`tidewater-actor-runtime-decoupling-001`** | `expert` | `tidewater` | Transformacja węzła w czysty automat Sans-I/O z protokołem efektów `OutboxEffect` | Całkowity zakaz odwołań węzła do kolejki zdarzeń, zachowanie 100% determinizmu śladów |

---

## 2. Zadanie 1: `atlas-pluggable-storage-engine-001`

### 2.1 Metadane i kontekst
* **ID:** `atlas-pluggable-storage-engine-001`
* **Trudność:** `expert`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/architecture/atlas-pluggable-storage-engine-001/`
* **Ziarno:** `datasets/_sources/atlas`
* **Ewaluator:** `pytest_evaluator` + `static_analysis_evaluator`

### 2.2 Opis problemu i zakres architektoniczny
Obecnie w `atlas` logika przechowywania danych jest ciasno spleciona z replikacją i mechanizmem anti-entropy w module `src/atlas/store.py` oraz `src/atlas/tables.py`. Węzeł bezpośrednio zarządza plikami i strukturami w pamięci, co uniemożliwia testowanie w pamięci bez dotykania dysku oraz blokuje wdrożenie innych formatów składowania.

Zadaniem agenta jest przeprowadzenie dużej refaktoryzacji architektonicznej:
1. Zdefiniowanie formalnego protokołu `StorageEngine(typing.Protocol)` w nowym module `src/atlas/storage/base.py`:
   - Metody: `get(key) -> VersionedRecord`, `put(record) -> bool`, `scan(range) -> Iterator`, `compact() -> None`, `flush() -> None`.
2. Zaimplementowanie dwóch konkretnych silników w `src/atlas/storage/`:
   - `MemoryStorageEngine`: ultraszybki silnik w pamięci RAM bazujący na posortowanych słownikach, dedykowany do testów i symulacji bez I/O.
   - `DiskStorageEngine`: istniejąca logika składowania wydzielona z `store.py` z zachowaniem atomowości i fencing tokenów.
3. Wstrzykiwanie silnika poprzez wzorzec Dependency Injection do `Node` i `ClusterRegistry`.
4. Zachowanie 100% kompatybilności publicznego API `atlas.store.AtlasStore`.

### 2.3 Dlaczego zadanie jest ekstremalnie trudne
Refaktoryzacja dotyka ponad 15 plików w projekcie. Zmiana granic warstw w rozproszonej bazie klucz-wartość grozi przerwaniem subtelnych założeń replikacji (np. kolejność aktualizacji wektorów zegarowych przed zapisem na dysk). Narzędzie analizy statycznej `tools/check_arch.py` rygorystycznie wymusza zakaz importów warstwy wyższej do niższej.

### 2.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`session_archive` (Kompaktowanie sesji):** Zadanie wymaga modyfikacji wielu modułów w 30–40 turach interakcji. Sesja regularnie przekracza limit tokenów i jest kompaktowana. Mechanizm `session_archive` przywraca dokładną definicję protokołów i interfejsów ustaloną na początku pracy.
* **`doc_context` & ADR:** Agent otrzymuje w kontekście `docs/adr/ADR-0008-storage-boundaries.md` oraz mapę nagłówków dokumentacji projektu.
* **`playbook`:** Po refaktoryzacji agent musi uruchomić walidator architektury: `python tools/check_arch.py --layers storage,replication,cluster`.
* **Tryby pracy (`agentic_routing_codex`):** Praca w trybie `plan` do analizy diagramu modułów, `implement` do edycji kodu, `test` do weryfikacji architektury.

### 2.5 Struktura katalogu i ewaluacja
```
datasets/architecture/atlas-pluggable-storage-engine-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_architecture_public.py
└── hidden_tests/
    ├── test_layer_boundaries.py
    ├── test_both_engines_contract.py
    └── arch_rules.json
```
* **Kryterium sukcesu:**
  1. `test_layer_boundaries.py` sprawdza graf AST projektu – brak zależności zwrotnych, `src/atlas/storage/` nie importuje `src/atlas/replication/`.
  2. Wszystkie testy jednostkowe i integracyjne `atlas` przechodzą na obu silnikach (`Memory` i `Disk`).
  3. `tools/check_arch.py` zwraca kod wyjścia 0.

---

## 3. Zadanie 2: `tidewater-actor-runtime-decoupling-001`

### 3.1 Metadane i kontekst
* **ID:** `tidewater-actor-runtime-decoupling-001`
* **Trudność:** `expert`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/architecture/tidewater-actor-runtime-decoupling-001/`
* **Ziarno:** `datasets/_sources/tidewater`
* **Ewaluator:** `pytest_evaluator` + `static_analysis_evaluator`

### 3.2 Opis problemu i zakres architektoniczny
W `tidewater` obiekt `Node` ma referencję do `Trace` oraz `NodeClock`. Mimo że węzeł nie wywołuje sieci bezpośrednio, jego stan wewnętrzny jest ściśle powiązany z pojęciem lokalnego czasu ticków i formatowaniem śladu.
Cel architektoniczny:
Przekształcenie `tidewater.node.Node` w czystą, deterministyczną maszynę stanową (Functional Core / Sans-I/O pattern):
1. `Node.step(event) -> tuple[NodeState, list[OutboxEffect]]`:
   - Węzeł nie mutuje własnego czasu ani nie rejestruje bezpośrednio śladów.
   - Wszystkie reakcje (wysłanie pakietu, reset timera, zapis rekordu, zgłoszenie zdarzenia trace) są zwracane jako niemutowalne rekordy `OutboxEffect`.
2. Utworzenie warstwy wykonawczej (Imperative Shell) w `src/tidewater/runtime/actor_runner.py`, która interpretuje efekty, zarządza zegarem i kieruje pakiety do kolejki sieciowej.
3. Nienaruszenie ani jednego testu zachowania protokołu Raft w klastrze symulacyjnym.

### 3.3 Dlaczego zadanie jest ekstremalnie trudne
Ekstrakcja efektów z wnętrza skomplikowanego protokołu wyborczego i replikacji logu wymaga rozbicia setek instrukcji przypisania na czyste kompozycje funkcyjne. Jeśli jakikolwiek efekt uboczny (np. persistencja termu w storage) zostanie wyemitowany w innej kolejności niż w seedzie, testy crash-consistency natychmiast oblewają.

### 3.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`recipe`:** Rozwiązanie problemu sekwencjonowania efektów `PersistBeforeReply` (zgodnie z `ADR-0012`) staje się uniwersalną receptą w bazie wiedzy.
* **`deadend`:** Próby zachowania ukrytego mutowalnego stanu w węźle zostają wykryte przez analizator czystości AST w testach ukrytych i odnotowane jako dead-end.
* **`doc_context`:** Wstrzyknięcie `docs/adr/ADR-0012-persist-before-reply.md` oraz `SPEC.md` sekcja 5.

### 3.5 Struktura katalogu i ewaluacja
```
datasets/architecture/tidewater-actor-runtime-decoupling-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_pure_node_public.py
└── hidden_tests/
    ├── test_effects_exhaustiveness.py
    ├── test_sans_io_purity.py
    └── test_trace_equality.py
```
* **Kryterium sukcesu:**
  1. `test_sans_io_purity.py` weryfikuje brak instrukcji I/O, brak importów modułów sieciowych i losowości w `src/tidewater/node.py`.
  2. `test_trace_equality.py` uruchamia wszystkie 12 harmonogramów referencyjnych i potwierdza zgodność z sumami kontrolnymi `traces/*.digest`.

---

## 4. Plan wdrożenia i weryfikacji

1. Aktywacja kategorii w `descriptors/categories/architecture.yaml` (`category.enabled: true`).
2. Implementacja skryptu analizy statycznej AST `tools/check_arch.py` sprawdzającego dozwolone relacje importów pomiędzy modułami.
3. Weryfikacja CLI: `.venv/bin/akbench dataset validate --task atlas-pluggable-storage-engine-001`.
