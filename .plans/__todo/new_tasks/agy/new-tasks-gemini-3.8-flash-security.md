# Plan implementacji zadań: Kategoria `security`

> **Kategoria:** `security` (Lokalizacja i załatanie podatności z zachowaniem integralności)  
> **Deskryptor kategorii:** `descriptors/categories/security.yaml`  
> **Dozwolone poziomy trudności:** `medium`, `hard`, `expert`  
> **Ewaluatory:** `pytest_evaluator`, `command_evaluator`

---

## 1. Przegląd zadań w kategorii `security`

| ID Zadania | Poziom | Ziarno (`_sources`) | Podatność do załatania | Ryzyko regresji / pułapka |
| :--- | :---: | :--- | :--- | :--- |
| **`tidewater-byzantine-timing-oracle-001`** | `expert` | `tidewater` | Timing / Pre-Vote Hijack: fałszowanie nagłówków czasowych detronizujące lidera | Odrzucenie legalnych komunikatów po uzdrowieniu partycji powoduje paraliż elekcji |
| **`atlas-vector-clock-forge-001`** | `hard` | `atlas` | Phantom generation injection: ominięcie fencing tokenów w wektorze zegarowym | Złamanie formatu wire API lub odrzucanie legalnego read-repair |

---

## 2. Zadanie 1: `tidewater-byzantine-timing-oracle-001`

### 2.1 Metadane i kontekst
* **ID:** `tidewater-byzantine-timing-oracle-001`
* **Trudność:** `expert`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/security/tidewater-byzantine-timing-oracle-001/`
* **Ziarno:** `datasets/_sources/tidewater`
* **Ewaluator:** `pytest_evaluator`

### 2.2 Opis problemu i wektor ataku
W standardowej implementacji `tidewater` węzły ufają polu `last_contact` wyliczanemu z nagłówków pakietów przychodzących.
Złośliwy lub wadliwie skonfigurowany węzeł (Byzantine / faulty node) może wysyłać pakiety `RequestVote` ze specjalnie spreparowanym ujemnym skewem czasowym oraz sztucznie zawyżonym termem, omijając mechanizm pre-vote.
Powoduje to:
1. Przymusowe zrzucenie roli aktywnego lidera (Leader Step-Down DoS) pomimo nienaruszonej większości w klastrze.
2. Wielokrotne sztuczne wybory (election churn), uniemożliwiające zatwierdzenie jakichkolwiek wpisów w maszynie stanowej.

Zadaniem agenta jest:
* Przebudowa mechanizmu weryfikacji dzierżawy lidera (`LeaderStickiness` / `ADR-0005`): węzeł bazuje wyłącznie na własnym, monotonicznym zegarze lokalnym `NodeClock`, odrzucając obce deklaracje czasowe w nagłówkach.
* Wdrożenie mechanizmu kwarantanny dla węzłów naruszających reguły kadencji (wykrywanie powtarzających się anomalii termu).
* Zapewnienie, że podczas normalnego podziału sieci (prawdziwa partycja i jej uzdrowienie) klaster potrafi bez przeszkód wybrać nowego lidera.

### 2.3 Dlaczego zadanie jest ekstremalnie trudne (Pętla błędów)
Zabezpieczenie przed atakiem timingowym w konsensusie jest klasycznym problemem antagonistycznym:
* Zbyt restrykcyjne ignorowanie wiadomości o wyższym termie zapobiega atakowi DoS, ale uniemożliwia legalną zmianę lidera po realnej awarii (klaster wisi $\rightarrow$ `ElectionTimeoutViolation`).
* Zbyt liberalne przyjmowanie termu otwiera podatność na nowo.
Agent bez dostępu do bazy postmortemów wpada w pętlę i wielokrotnie próbuje nieskutecznych reguł filtrowania.

### 2.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`knowledge-or-escalate`:** Model oscylujący pomiędzy zbyt twardym a zbyt miękkim filtrem powtarza ten sam błąd weryfikacji. Po 3 iteracjach następuje eskalacja modelu do `27B`.
* **`deadend`:** Zapisywanie nieudanych prób filtrowania bazujących na `msg.timestamp`.
* **`doc_context`:** Wstrzyknięcie `docs/incidents/INC-0007-fast-clock-node-kept-deposing-the-leader.md` oraz `docs/adr/ADR-0005-linearizable-read-lease.md`.
* **`recipe`:** Poprawna reguła oparta o lokalny timer dzierżawy zostaje utrwalona jako `recipe`.

### 2.5 Struktura katalogu i ewaluacja
```
datasets/security/tidewater-byzantine-timing-oracle-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_timing_security_public.py
└── hidden_tests/
    ├── test_byzantine_attack_vectors.py
    ├── test_legitimate_partition_healing.py
    └── schedules/
        ├── attack_timed_dos.json
        └── normal_heal.json
```
* **Kryterium sukcesu:**
  1. `test_byzantine_attack_vectors.py`: atak DoS zostaje odparty, aktywny lider utrzymuje pozycję i zatwierdza transakcje.
  2. `test_legitimate_partition_healing.py`: normalny failover po padzie lidera działa w czasie $< 2.5 \times \text{election\_timeout}$.

---

## 3. Zadanie 2: `atlas-vector-clock-forge-001`

### 3.1 Metadane i kontekst
* **ID:** `atlas-vector-clock-forge-001`
* **Trudność:** `hard`
* **Limit czasu:** 10800 s (3h)
* **Katalog:** `datasets/security/atlas-vector-clock-forge-001/`
* **Ziarno:** `datasets/_sources/atlas`
* **Ewaluator:** `pytest_evaluator`

### 3.2 Opis problemu i wektor ataku
W `atlas` wektor zegarowy (`src/atlas/vclock.py`) jest przekazywany w żądaniach klientów w celu śledzenia przyczynowości zdarzeń (causal ordering). Z powodu braku walidacji integralności identyfikatorów węzłów w tokenie generacji, spreparowane żądanie `PUT` z wstrzykniętym "phantom generation" pozwala złośliwemu klientowi sfingować konflikt wersji.
W efekcie:
1. Read-repair wymusza propagację wartości klienta jako "najnowszej" w procedurze rozstrzygania remisów (`descending tie-break`), nadpisując legalne zapisy innych użytkowników bez ostrzeżenia.
2. Zostaje złamana gwarancja niezmiennika atomowego commitu.

Zadaniem agenta jest:
* Wdrożenie kryptograficznie bezpiecznej walidacji generacji i węzłów (token HMAC lub kryptograficzny digest przypisany do topologii shardingu).
* Zachowanie wstecznej kompatybilności serializacji JSON bez zmiany formatu wire API dla uczciwych węzłów.
* Wykrywanie i odrzucanie sfingowanych vclocków z kodem błędu `SecurityViolationError`.

### 3.3 Dlaczego zadanie jest ekstremalnie trudne
Naiwne dodanie podpisu zmienia długość i schemat wektora zegarowego, co powoduje odrzucenie pakietów przez starsze komponenty replikacji w klastrze (`WireFormatError`). Agent musi wdrożyć bezpieczne rozszerzenie nagłówka w sposób niewidoczny dla parsowania bazowego, ściśle według specyfikacji protokołu.

### 3.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`doc_context`:** Wstrzyknięcie `docs/adr/ADR-0003-vector-clock-invariants.md` oraz `SPEC.md` sekcja 4.
* **`playbook`:** Procedura ponownego generowania tabel schematów przy użyciu `tools/gen_tables.py --verify-signatures`.
* **`recipe`:** Prawidłowa integracja walidatora HMAC w `src/atlas/fencing.py` staje się bazową receptą w bazie SSE.

### 3.5 Struktura katalogu i ewaluacja
```
datasets/security/atlas-vector-clock-forge-001/
├── task.yaml
├── description.md
├── public_tests/
│   └── test_vclock_validation_public.py
└── hidden_tests/
    ├── test_forge_exploit_mitigated.py
    ├── test_wire_format_backcompat.py
    └── malicious_payloads.json
```
* **Kryterium sukcesu:**
  1. `test_forge_exploit_mitigated.py`: wszystkie próby wstrzyknięcia phantom generation kończą się odrzuceniem zapisu.
  2. `test_wire_format_backcompat.py`: poprawna komunikacja pomiędzy węzłami zaktualizowanymi i węzłami w trakcie migracji.

---

## 4. Plan wdrożenia i weryfikacji

1. Aktywacja kategorii w `descriptors/categories/security.yaml` (`category.enabled: true`).
2. Przygotowanie wektorów ataków w `hidden_tests/` w postaci precyzyjnych scenariuszy testowych.
3. Weryfikacja CLI: `.venv/bin/akbench dataset validate --task tidewater-byzantine-timing-oracle-001`.
