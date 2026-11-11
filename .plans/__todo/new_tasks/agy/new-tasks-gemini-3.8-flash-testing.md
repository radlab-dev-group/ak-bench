# Plan implementacji zadań: Kategoria `testing`

> **Kategoria:** `testing` (Pisanie testów wyłapujących specyficzne defekty / pokrycie brzegowe)  
> **Deskryptor kategorii:** `descriptors/categories/testing.yaml`  
> **Dozwolone poziomy trudności:** `easy`, `medium`, `hard`  
> **Ewaluatory:** `pytest_evaluator`, `command_evaluator`

---

## 1. Przegląd zadań w kategorii `testing`

| ID Zadania | Poziom | Ziarno (`_sources`) | Cel testowy | Warunek zaliczenia |
| :--- | :---: | :--- | :--- | :--- |
| **`tidewater-chaos-schedule-synthesis-001`** | `hard` | `tidewater` | Opracowanie deterministycznego harmonogramu błędów (`schedules/byzantine-partition.json`) | Wymuszenie wyścigu w elekcji ściśle w oknie ticków [1200, 1400] na mutancie, brak fałszywych alarmów na kodzie poprawnym |
| **`atlas-property-based-fencing-suite-001`** | `hard` | `atlas` | Opracowanie zestawu testów property-based (stanowych) dla protokołu fencing | Wykrycie 4 subtelnych defektów rebalance i anti-entropy z zerową liczbą false-positives |

---

## 2. Zadanie 1: `tidewater-chaos-schedule-synthesis-001`

### 2.1 Metadane i kontekst
* **ID:** `tidewater-chaos-schedule-synthesis-001`
* **Trudność:** `hard`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/testing/tidewater-chaos-schedule-synthesis-001/`
* **Ziarno:** `datasets/_sources/tidewater`
* **Ewaluator:** `command_evaluator` + `pytest_evaluator`

### 2.2 Opis problemu i zakres zadania
Symulator `tidewater` opiera się na plikach harmonogramów `schedules/*.json`. Agent nie modyfikuje kodu symulatora w `src/`, lecz musi zaprojektować nowy, deterministyczny scenariusz testowy w `schedules/byzantine-partition.json` oraz powiązany test w `tests/test_chaos_schedules.py`.

Scenariusz musi:
1. Zbudować topologię 5 węzłów z asymetrycznym opóźnieniem łączy (`delay_range: [15, 45]`).
2. W ticku 500 podzielić sieć na dwie partycje (`{n1, n2}` oraz `{n3, n4, n5}`).
3. W ticku 1200 wstrzyknąć awarię zegara w węźle `n3` (`ClockSkewAction`), symulując gwałtowny skok o $+200$ ticków, i natychmiast uzdrowić łącze do `n1`.
4. Cel testu: Wymusić w wadliwej wersji symulatora (`mutated_tidewater`) naruszenie niezmiennika `SafetyViolation: election_safety` w oknie $[1200, 1400]$, podczas gdy na wersji referencyjnej klastra test musi przejść pomyślnie i potwierdzić zbieżność.
5. Zaktualizować manifest `schedules/MANIFEST` przy pomocy oficjalnego narzędzia.

### 2.3 Dlaczego zadanie jest trudne
Projektowanie deterministycznych testów chaosu w systemach rozproszonych wymaga matematycznej precyzji: najmniejsze niedoszacowanie czasu trwania election timeoutu lub niepoprawna konfiguracja drop-ratio powoduje, że wyścig nie zachodzi lub zachodzi poza zadanym oknem ticków.

### 2.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`playbook`:** Po utworzeniu pliku harmonogramu agent musi zaktualizować manifest: `python tools/gen_schedules.py --lock`. Narzędzie sprawdza poprawność schematu JSON i liczy skróty SHA-256.
* **`doc_context`:** Wstrzyknięcie `docs/schedule-spec.md` oraz specyfikacji akcji w symulatorze.
* **`tryb test` w `auto_codex`:** Router automatycznie kieruje agenta do mocniejszego modelu `Qwen-27B` podczas tworzenia i walidacji kodu testowego.

### 2.5 Struktura katalogu i ewaluacja
```
datasets/testing/tidewater-chaos-schedule-synthesis-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_schedule_syntax_public.py
└── hidden_tests/
    ├── test_catches_mutant_defect.py
    └── test_passes_on_golden_seed.py
```
* **Kryterium sukcesu:**
  1. `test_passes_on_golden_seed.py`: test agenta przechodzi na nienaruszonym kodzie `tidewater`.
  2. `test_catches_mutant_defect.py`: test agenta bezbłędnie oblewa na 3 przygotowanych zmutowanych wersjach węzła, wskazując błąd `election_safety` dokładnie w zadanym przedziale ticków.

---

## 3. Zadanie 2: `atlas-property-based-fencing-suite-001`

### 3.1 Metadane i kontekst
* **ID:** `atlas-property-based-fencing-suite-001`
* **Trudność:** `hard`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/testing/atlas-property-based-fencing-suite-001/`
* **Ziarno:** `datasets/_sources/atlas`
* **Ewaluator:** `pytest_evaluator`

### 3.2 Opis problemu i zakres zadania
W rozproszonym magazynie `atlas` testy jednostkowe pokrywają proste scenariusze sekwencyjne, ale rzadkie wyścigi w anti-entropy i fencing tokenach uciekają tradycyjnym asercjom.
Zadaniem agenta jest napisanie zaawansowanego modułu testów stanowych (Stateful Testing) w `tests/test_fencing_stateful.py`:
1. Model maszyny stanowej generujący losowe, ale deterministyczne (sterowane seedem) sekwencje:
   - `write_key(k, v)`, `rebalance_shard(shard_id, src, dst)`, `partition_node(node_id)`, `crash_and_recover(node_id)`.
2. Asercja niezmiennika liniowości (Linearizability Oracle): odczyt `get(k)` w dowolnym węźle musi być spójny z formalną historią zdarzeń i wektorami zegarowymi.
3. Zestaw testów musi automatycznie zlokalizować 4 znane defekty z rodziny `atlas-drift` w czasie poniżej 120 sekund.

### 3.3 Dlaczego zadanie jest trudne
Generatory testów losowych często generują "szum" – miliony operacji, które albo nie trafiają w okno błędu, albo powodują fałszywe alarmy (false positives) z powodu niezrozumienia reguł eventual consistency. Agent musi precyzyjnie zaimplementować regułę descending tie-break z `ADR-0003`.

### 3.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`doc_context`:** Iniekcja `docs/incidents/INC-1201` – `INC-1204` jako specyfikacji objawów, które test musi wykrywać.
* **`deadend`:** Zapisanie błędnych założeń orzecznika liniowości, które zgłaszały false-positive na poprawnym seedzie.
* **`recipe`:** Gotowy wzorzec orzecznika liniowości staje się receptą w bazie wiedzy.

### 3.5 Struktura katalogu i ewaluacja
```
datasets/testing/atlas-property-based-fencing-suite-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_suite_structure_public.py
└── hidden_tests/
    ├── test_mutant_detection_power.py
    └── test_zero_false_positives_on_clean_seed.py
```
* **Kryterium sukcesu:**
  1. Wykrycie wszystkich 4 mutantów `atlas-drift-001` .. `004`.
  2. 0 false-positives na 1000 wygenerowanych operacji na czystym seedzie.

---

## 4. Plan wdrożenia i weryfikacji

1. Aktywacja kategorii w `descriptors/categories/testing.yaml` (`category.enabled: true`).
2. Przygotowanie mutantów referencyjnych w `hidden_tests/` sprawdzających siłę wykrywania testów agenta.
3. Weryfikacja CLI: `.venv/bin/akbench dataset validate --task tidewater-chaos-schedule-synthesis-001`.
