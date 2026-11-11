# Plan implementacji zadań: Kategoria `debugging`

> **Kategoria:** `debugging` (Diagnoza awarii na podstawie śladu/logu i usunięcie jej pierwotnej przyczyny)  
> **Deskryptor kategorii:** `descriptors/categories/debugging.yaml`  
> **Dozwolone poziomy trudności:** `easy`, `medium`, `hard`  
> **Ewaluatory:** `pytest_evaluator`, `command_evaluator`

---

## 1. Przegląd zadań w kategorii `debugging`

| ID Zadania | Poziom | Ziarno (`_sources`) | Scenariusz błędu / Objaw | Źródło dowodowe |
| :--- | :---: | :--- | :--- | :--- |
| **`tidewater-postmortem-trace-triangulation-001`** | `hard` | `tidewater` | `SafetyViolation: state_machine_safety` po 2500 tickach symulacji | 15 MB zrzutu JSONL (`incident_trace.jsonl`) bez wskazania linii kodu |
| **`walqueue-silent-corruption-triage-001`** | `hard` | `walqueue` | Cicha korupcja 12 bajtów rekordu przy rotacji segmentu podczas braku miejsca (`ENOSPC`) | Zrzut heksadecymalny zepsutego segmentu + core dump procesu |

---

## 2. Zadanie 1: `tidewater-postmortem-trace-triangulation-001`

### 2.1 Metadane i kontekst
* **ID:** `tidewater-postmortem-trace-triangulation-001`
* **Trudność:** `hard`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/debugging/tidewater-postmortem-trace-triangulation-001/`
* **Ziarno:** `datasets/_sources/tidewater`
* **Ewaluator:** `pytest_evaluator`

### 2.2 Opis problemu i zakres diagnostyczny
W środowisku produkcyjnym symulatora wygenerowano 15-megabajtowy ślad `incident_trace.jsonl` obejmujący 3000 ticków klastra z wieloma awariami. W ticku 2580 monitor zgłosił błąd:
`SafetyViolation at tick 2580: state_machine_safety: node n2 applied command 'set x=4' at index 48, but committed record has 'set x=9'`.
Kod repozytorium zawiera subtelny błąd w mechanizmie buforowania niezastosowanych wpisów logu w `src/tidewater/node.py` przy restarcie węzła.

Zadaniem agenta jest:
1. **Triangulacja śladu (Trace Triangulation):** Napisanie skryptu diagnostycznego lub użycie narzędzi CLI (`tools/replay_trace.py`) do odnalezienia pierwszego momentu dywergencji (first point of divergence) w gigantycznym logu.
2. Zlokalizowanie pierwotnej przyczyny (Root Cause): udowodnienie, że błąd w ticku 2580 był skutkiem zdarzenia w ticku 612 (opóźniony pakiet `AppendEntries` nadpisał wskaźnik `last_applied` przed zakończeniem odtwarzania ze storage).
3. Naprawa usterki w `src/tidewater/node.py` bez wprowadzania regresji do innych mechanizmów replikacji.
4. Dostarczenie minimalnego testu regresyjnego (`tests/test_incident_reproduction.py`) opartego o harmonogram liczący mniej niż 100 ticków.

### 2.3 Dlaczego zadanie jest trudne
15 megabajtów logu JSONL (ponad 80 000 linii tekstu) wielokrotnie przekracza okno kontekstowe każdego modelu LLM. Naiwne próby wklejenia logu do czatu kończą się błędem `ContextWindowExceeded` lub chaotycznymi halucynacjami małego modelu. Agent musi umieć posługiwać się narzędziami terminala (`grep`, `jq`, `tools/replay_trace.py`), aby zredukować przestrzeń poszukiwań.

### 2.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`compaction` & `session_archive`:** Ponieważ analiza dużego pliku i uruchamianie kolejnych filtrów shellowych trwa wiele kroków, sesja ulega kompaktowaniu. Mechanizm `session_archive` zachowuje wstrzyknięte do bazy kluczowe numery ticków (`tick 612`, `index 48`) sprzed kompresji.
* **Tryb `debug` w `auto_codex`:** Router automatycznie aktywuje tryb `debug` po wykryciu słów kluczowych "SafetyViolation", "triangulate", "divergence".
* **`knowledge-or-escalate`:** Jeśli agent wielokrotnie proponuje poprawkę w złym miejscu (np. w `statemachine.py` zamiast w logice odtwarzania w `node.py`), licznik pętli błędu osiąga 3 i następuje eskalacja na większy model.
* **`doc_context`:** Wstrzyknięcie `docs/incidents/INC-0003-follower-lost-committed-entries-after-restart.md` naprowadzające na analogiczne problemy z odtwarzaniem stanu.

### 2.5 Struktura katalogu i ewaluacja
```
datasets/debugging/tidewater-postmortem-trace-triangulation-001/
├── task.yaml
├── description.md
├── incident/
│   ├── incident_report.md
│   └── incident_trace.jsonl.gz
├── public_tests/
│   └── test_reproduction_syntax_public.py
└── hidden_tests/
    ├── test_root_cause_fixed.py
    └── test_minimal_reproducer_valid.py
```
* **Kryterium sukcesu:**
  1. `test_root_cause_fixed.py`: pełny scenariusz incydentu przechodzi bez zgłoszenia wyjątku `SafetyViolation`.
  2. `test_minimal_reproducer_valid.py`: dostarczony reproduktor odtwarza defekt w czasie $< 2$ sekund.

---

## 3. Zadanie 2: `walqueue-silent-corruption-triage-001`

### 3.1 Metadane i kontekst
* **ID:** `walqueue-silent-corruption-triage-001`
* **Trudność:** `hard`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/debugging/walqueue-silent-corruption-triage-001/`
* **Ziarno:** `datasets/_sources/walqueue`
* **Ewaluator:** `pytest_evaluator`

### 3.2 Opis problemu i zakres diagnostyczny
Klient systemu `walqueue` zgłasza sporadyczną utratę ostatnich rekordów kolejki po awarii zasilania serwera w trakcie zapełniania dysku. Logi systemowe wskazują na błąd `OSError: [Errno 28] No space left on device` podczas rotacji pliku segmentu. Po restarcie wskaźnik odczytu (`consumer_offset`) wskazuje na uszkodzony rekord z sumą kontrolną równą zeru, blokując cały proces odczytu.

Zadaniem agenta jest:
1. Zbadanie dostarczonego zrzutu uszkodzonego segmentu w `incident/corrupted_segment.wal`.
2. Diagnoza: odnalezienie błędu w `src/walqueue/segment.py`, gdzie obsługa wyjątku `OSError` cofa offset w pamięci, ale nie usuwa częściowo zapisanego nagłówka (torn header) z bufora jądra, co przy kolejnym zapisie tworzy lukę bajtową.
3. Wdrożenie atomowego cofania stanu i obcinania pliku (`os.ftruncate`) do ostatniego potwierdzonego offsetu.
4. Napisanie testu weryfikującego odporność na `ENOSPC`.

### 3.3 Dlaczego zadanie jest trudne
Diagnoza uszkodzeń binarnych plików wymaga zrozumienia różnicy pomiędzy buforowaniem na poziomie biblioteki standardowej Pythona (`io.BufferedWriter`), buforem jądra (page cache) a fizycznym stanem pliku na dysku. Błędna poprawka wywołuje regresję wydajnościową lub korupcję całego indeksu.

### 3.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`deadend`:** Proste wyzerowanie sprawdzania CRC32 zostaje odrzucone przez testy integralności i wpisane jako zakazane podejście.
* **`recipe`:** Wzorzec atomowego obcinania pliku z uaktualnieniem nagłówka segmentu staje się receptą w bazie SSE.
* **`doc_context`:** Iniekcja `docs/adr/ADR-0002-segment-recovery-protocol.md`.

### 3.5 Struktura katalogu i ewaluacja
```
datasets/debugging/walqueue-silent-corruption-triage-001/
├── task.yaml
├── description.md
├── incident/
│   ├── corrupted_segment.wal
│   └── crash_backtrace.txt
├── public_tests/
│   └── test_triage_public.py
└── hidden_tests/
    ├── test_enospc_resilience.py
    └── test_clean_recovery.py
```
* **Kryterium sukcesu:**
  1. `test_enospc_resilience.py`: symulacja braku miejsca na dysku nie pozostawia częściowych rekordów.
  2. `test_clean_recovery.py`: restart po awarii poprawnie wznawia odczyt od ostatniego prawidłowego rekordu.

---

## 4. Plan wdrożenia i weryfikacji

1. Aktywacja kategorii w `descriptors/categories/debugging.yaml` (`category.enabled: true`).
2. Przygotowanie artefaktów incydentów (logi JSONL, zrzuty binarne segmentów) w katalogach zadań.
3. Weryfikacja CLI: `.venv/bin/akbench dataset validate --task tidewater-postmortem-trace-triangulation-001`.
