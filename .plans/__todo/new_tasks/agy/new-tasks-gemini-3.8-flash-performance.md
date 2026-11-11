# Plan implementacji zadań: Kategoria `performance`

> **Kategoria:** `performance` (Optymalizacja wydajności z zachowaniem poprawności i niezmienników)  
> **Deskryptor kategorii:** `descriptors/categories/performance.yaml`  
> **Dozwolone poziomy trudności:** `medium`, `hard`, `expert`  
> **Ewaluatory:** `pytest_evaluator`, `command_evaluator` (deterministyczna uprząż pomiarowa)

---

## 1. Przegląd zadań w kategorii `performance`

| ID Zadania | Poziom | Ziarno (`_sources`) | Główny cel optymalizacji | Niezmiennik podlegający obronie |
| :--- | :---: | :--- | :--- | :--- |
| **`tidewater-eventloop-throughput-001`** | `expert` | `tidewater` | Skrócenie czasu symulacji klastra Raft o $\ge 65\%$ i alokacji o $\ge 80\%$ | Ścisły determinizm śladów (`traces/*.digest`) i kolejność zdarzeń |
| **`walqueue-zerocopy-io-001`** | `expert` | `walqueue` | 4-krotny wzrost przepustowości zapisu append-only WAL z buforowaniem zerokopiowym | Atomowość flusha `fsync` i brak korupcji przy crash-recovery |

---

## 2. Zadanie 1: `tidewater-eventloop-throughput-001`

### 2.1 Metadane i kontekst
* **ID:** `tidewater-eventloop-throughput-001`
* **Trudność:** `expert`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/performance/tidewater-eventloop-throughput-001/`
* **Ziarno:** `datasets/_sources/tidewater`
* **Ewaluator:** `command_evaluator` + `pytest_evaluator`

### 2.2 Opis problemu i wyzwanie techniczne
W symulatorze `tidewater` pętla zdarzeń w `src/tidewater/cluster.py` (`Cluster.step()`) oraz kolejka zdarzeń `src/tidewater/clock.py` (`EventQueue`) są wąskim gardłem przy długich symulacjach (np. 10 000 ticków, 50 węzłów, setki tysięcy pakietów RPC).
Problemy wydajnościowe wynikają z:
1. Naiwnego sortowania listy `list.sort()` przy każdym wstawieniu i wyjęciu zdarzenia w `EventQueue` ($O(N \log N)$ na operację).
2. Nadmiarowej alokacji obiektów `Envelope` i `Message` kopiowanych w każdej iteracji kolejkowania sieciowego.
3. Sprawdzania niezmienników `InvariantMonitor.check()` w każdym ticku w sposób pełny zamiast inkrementalnego.

Zadaniem agenta jest:
* Zastąpienie kolejki strukturą opartą na `heapq` z deterministycznym rozstrzyganiem remisów (stabilne tie-breaking krotek bez naruszania kolejności zdarzeń z tego samego ticku).
* Wdrożenie puli obiektów / slotów dla bufora outbox bez niepotrzebnych klonowań słowników metadanych.
* Wdrożenie inkrementalnego śledzenia zmian w `InvariantMonitor`, sprawdzającego tylko węzły, które przetworzyły pakiety w danym ticku.

### 2.3 Dlaczego zadanie jest ekstremalnie trudne
Nawet minimalna zmiana kolejności iteracji po węzłach lub niestabilne sortowanie w `heapq` zmienia kolejność generowania zdarzeń `trace`, co natychmiast powoduje niezgodność z `traces/*.digest`. Zadanie wymaga osiągnięcia rygorystycznego progu czasu CPU bez zmiany ani jednego bajta w wyjściu symulacji.

### 2.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`playbook`:** Agent musi w każdej iteracji uruchamiać procedurę profilowania z `tools/bench.py --ticks 10000 --seed 42 --json-out bench.json` i porównywać metryki z baseline.
* **`deadend`:** Zastąpienie sortowania prostym buforem FIFO łamie przyczynowo-skutkową kolejność dostarczania pakietów (błąd `SafetyViolation: election_safety`). Baza wiedzy rejestruje to podejście jako `deadend`.
* **`compaction`:** Profile wydajnościowe (zrzuty cProfile i statystyki alokacji tracemalloc) liczą setki linii i szybko zapełniają okno kontekstu Codexa. Wymuszone kompaktowanie sesji korzysta z `session_archive` do zachowania bazowych pomiarów czasowych.
* **`doc_context`:** Wstrzyknięcie `docs/adr/ADR-0001-logical-time-and-phase-order.md` jako normatywnej zasady określającej kolejność faz w ticku.

### 2.5 Struktura katalogu i ewaluacja
```
datasets/performance/tidewater-eventloop-throughput-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_throughput_public.py
└── hidden_tests/
    ├── test_invariants_preserved.py
    ├── bench_harness.py
    └── baseline_metrics.json
```
* **Kryterium sukcesu:**
  1. `bench_harness.py` wykonuje symulację 10 000 ticków w czasie $< 35\%$ czasu bazowego (ponad 2.85x przyspieszenie).
  2. Liczba alokacji pamięci zredukowana o $\ge 80\%$.
  3. Pełny pakiet testów `pytest tests/` oraz `tools/reference_traces.py --check` przechodzi w 100% (zero dywergencji).

---

## 3. Zadanie 2: `walqueue-zerocopy-io-001`

### 3.1 Metadane i kontekst
* **ID:** `walqueue-zerocopy-io-001`
* **Trudność:** `expert`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/performance/walqueue-zerocopy-io-001/`
* **Ziarno:** `datasets/_sources/walqueue`
* **Ewaluator:** `command_evaluator` + `pytest_evaluator`

### 3.2 Opis problemu i wyzwanie techniczne
W silniku `walqueue` zapis rekordów do dziennika WAL wykonuje wielokrotne alokacje pośrednie: serializacja do bajtów, konkatenacja nagłówka z payloadem, obliczanie CRC32 na nowym buforze i wywołanie `file.write()`. Przy obciążeniu rzędu 50 000 operacji/s tworzy to potężny narzut na Garbage Collector i blokuje I/O.

Zadaniem agenta jest:
1. Przepisanie warstwy zapisu na bufor cykliczny `bytearray` z obsługą `memoryview` (zero-copy buffer slicing).
2. Zastosowanie inkrementalnego obliczania `zlib.crc32` bezpośrednio na fragmentach pamięci bez tworzenia stringów/bajtów pośrednich.
3. Wdrożenie adaptacyjnego grupowania flushy (group commit z zadanym limitem mikrosekund lub bajtów), sterowanego przez `SyncPolicy.GROUP_BATCH`.
4. Zachowanie gwarancji: w razie symulowanej awarii zasilania (`SIGKILL` w procesie potomnym) żaden rekord potwierdzony klientowi nie może zostać uszkodzony ani utracony.

### 3.3 Dlaczego zadanie jest ekstremalnie trudne
Optymalizacje I/O z buforowaniem zerokopiowym w Pythonie są podatne na błędy wyścigu przy modyfikacji bufora pod spodem `memoryview` oraz na błędy ucięcia danych (torn writes) przy awarii w trakcie zapisu nagłówka rekordu. Testy ukryte zawierają uprząż wstrzykującą przerwania w dowolnym bajcie strumienia.

### 3.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`recipe`:** Rozwiązanie problemu barier pamięci przy `memoryview` w połączeniu z `os.fdatasync` zostaje zarejestrowane jako `recipe` i wykorzystane w kolejnych fazach zadania.
* **`deadend`:** Zbyt agresywny bufor w pamięci bez flusha przed odpowiedzią do klienta oblewa crash-recovery tests. Agent, który próbuje oszukać benchmark przez pomijanie `fsync`, trafia na dead-end w bazie wiedzy.
* **`docs/adr`:** Wstrzyknięcie dokumentu `docs/adr/ADR-0004-fsync-batching.md` określającego rygory trwałości.

### 3.5 Struktura katalogu i ewaluacja
```
datasets/performance/walqueue-zerocopy-io-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_zerocopy_public.py
└── hidden_tests/
    ├── test_crash_resilience.py
    ├── perf_bench.py
    └── baseline_io.json
```
* **Kryterium sukcesu:**
  1. `perf_bench.py` wykazuje przepustowość $\ge 4.0\times$ w stosunku do baseline na dyskowym benchmarku synchronicznym.
  2. Test `test_crash_resilience.py` wykonuje 50 symulacji awarii i weryfikuje brak błędów CRC32 oraz spójność wskaźników odczytu.

---

## 4. Plan wdrożenia i weryfikacji

1. Aktywacja kategorii w `descriptors/categories/performance.yaml` (`category.enabled: true`).
2. Przygotowanie harnessów pomiarowych w `hidden_tests/` z deterministycznym pomiarem czasu CPU (użycie `time.process_time()` zamiast `time.time()` w celu wyeliminowania fluktuacji środowiska).
3. Wygenerowanie stabilnych plików `baseline_metrics.json` na środowisku wzorcowym.
4. Weryfikacja CLI: `.venv/bin/akbench dataset validate --task tidewater-eventloop-throughput-001`.
