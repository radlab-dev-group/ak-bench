# Plan implementacji zadań: Kategoria `code_review`

> **Kategoria:** `code_review` (Identyfikacja subtelnych luk i naruszeń niezmienników w proponowanych zmianach PR)  
> **Deskryptor kategorii:** `descriptors/categories/code_review.yaml`  
> **Dozwolone poziomy trudności:** `easy`, `medium`, `hard`  
> **Ewaluatory:** `pytest_evaluator`, `command_evaluator`

---

## 1. Przegląd zadań w kategorii `code_review`

| ID Zadania | Poziom | Ziarno (`_sources`) | Przedmiot recenzji (Pull Request) | Oczekiwane znaleziska (Review Targets) |
| :--- | :---: | :--- | :--- | :--- |
| **`tidewater-joint-consensus-pr-review-001`** | `hard` | `tidewater` | PR wprowadzający Joint Consensus (`membership.py`, +420 linii) | 3 krytyczne błędy naruszające regułę podwójnej większości i ucinanie starych konfiguracji |
| **`atlas-antientropy-merkle-pr-review-001`** | `hard` | `atlas` | PR optymalizujący drzewa Merkle'a w anti-entropy (+380 linii) | 2 błędy współbieżności i 1 błąd brzegowy w wyliczaniu zakresu hashy |

---

## 2. Zadanie 1: `tidewater-joint-consensus-pr-review-001`

### 2.1 Metadane i kontekst
* **ID:** `tidewater-joint-consensus-pr-review-001`
* **Trudność:** `hard`
* **Limit czasu:** 7200 s (2h)
* **Katalog:** `datasets/code_review/tidewater-joint-consensus-pr-review-001/`
* **Ziarno:** `datasets/_sources/tidewater`
* **Ewaluator:** `pytest_evaluator` (weryfikator ustrukturyzowanego raportu review)

### 2.2 Opis problemu i zakres zadania
Agent otrzymuje diff pull requesta `pr_diff.patch` modyfikujący moduł `src/tidewater/membership.py` oraz `src/tidewater/node.py`. Zmiana rzekomo wdraża dynamiczną rekonfigurację klastra (Joint Consensus wg Raft Paper §6).
Autor PR-a deklaruje, że kod jest poprawny i testy jednostkowe przechodzą na zielono.

W rzeczywistości PR zawiera 3 głęboko ukryte usterki logiczne:
1. **Luka 1 (Brak podwójnej większości przy wyborach):** W stanie konfiguracji przejściowej `C_old,new` metoda `JointConfiguration.has_majority()` zwraca `True`, jeśli zwykła suma głosów ze starej i nowej konfiguracji przekracza połowę całości, zamiast wymagać niezależnej większości w **obu** podgrupach osobno (`SPEC.md` sekcja 7.2). Umożliwia to split-brain.
2. **Luka 2 (Przedwczesne przejście do `C_new`):** Lider wysyła wpis `C_new` natychmiast po otrzymaniu odpowiedzi od większości na wpis `C_old,new`, zanim wpis przejściowy zostanie formalnie zatwierdzony (`commit_index >= joint_entry.index`).
3. **Luka 3 (Usunięcie lidera bez zrzucenia roli):** Jeśli nowa konfiguracja `C_new` nie zawiera obecnego lidera, lider kontynuuje replikację i heartbeaty zamiast zrzucić rolę do followera natychmiast po zatwierdzeniu wpisu `C_new`.

Zadaniem agenta jest:
* Wygenerowanie ustrukturyzowanego pliku raportu recenzji `review_findings.json` (zgodnego ze schematem walidacyjnym).
* Wskazanie dla każdego problemu: pliku, przedziału linii, kategorii błędu (`invariant_violation`), cytatu normatywnego z dokumentacji (`SPEC.md` / `ADR`) oraz propozycji poprawnego rozwiązania.

### 2.3 Dlaczego zadanie jest trudne
Kod w diffie wygląda bardzo przekonująco: używa eleganckich dataclass, ma poprawne type hinting i przechodzi podstawowe testy. Prosty model językowy bez znajomości specyfikacji chwali kod za styl, nie zauważając subtelnych naruszeń teorii konsensusu rozproszonego.

### 2.4 Integracja z `auto_codex` i `agentic_knowledge`
* **Tryb `review` / `git_review` w `auto_codex`:** Router automatycznie rozpoznaje zapytanie o review diffa i kieruje zapytanie do dedykowanego promptu analitycznego.
* **`doc_context`:** Wstrzyknięcie `SPEC.md` sekcja 7 oraz `docs/adr/ADR-0009-joint-consensus-commit-boundary.md` do kontekstu agenta.
* **`deadend`:** Zignorowanie powierzchownych uwag linterowych (np. brak docstringa) – testy ukryte punktują wyłącznie wykrycie 3 kluczowych wad algorytmicznych.

### 2.5 Struktura katalogu i ewaluacja
```
datasets/code_review/tidewater-joint-consensus-pr-review-001/
├── task.yaml
├── description.md
├── review_target/
│   ├── pr_diff.patch
│   └── pr_description.md
├── public_tests/
│   └── test_review_schema_public.py
└── hidden_tests/
    ├── test_review_accuracy_hidden.py
    └── goldens/
        └── expected_findings.json
```
* **Kryterium sukcesu:**
  1. `test_review_accuracy_hidden.py` sprawdza `review_findings.json`:
     - Wykrycie wszystkich 3 krytycznych luk ($100\%$ Recall dla celów recenzji).
     - Precyzja $\ge 85\%$ (brak halucynacji o nieistniejących błędach składniowych).
     - Prawidłowe wskazanie naruszonego punktu `SPEC.md`.

---

## 3. Zadanie 2: `atlas-antientropy-merkle-pr-review-001`

### 3.1 Metadane i kontekst
* **ID:** `atlas-antientropy-merkle-pr-review-001`
* **Trudność:** `hard`
* **Limit czasu:** 7200 s (2h)
* **Katalog:** `datasets/code_review/atlas-antientropy-merkle-pr-review-001/`
* **Ziarno:** `datasets/_sources/atlas`
* **Ewaluator:** `pytest_evaluator`

### 3.2 Opis problemu i zakres zadania
W pull requeście do `atlas` autor optymalizuje wymianę metadanych anti-entropy w `src/atlas/antientropy.py`, wprowadzając hierarchiczne drzewa skrótów (Merkle Trees) zamiast płaskich skanów wektorów zegarowych.
PR zawiera:
1. **Luka 1 (Off-by-one w granicy hashy):** Obliczanie hasha liścia drzewa używa przedziału prawostronnie otwartego `[start, end)`, podczas gdy partycjonowanie kluczy w pierścieniu bazuje na przedziale obustronnie domkniętym `[start, end]`. W rezultacie klucze o hashu równym dokładnie `end` są pomijane w procedurze naprawy anti-entropy.
2. **Luka 2 (Wyścig z mutacją w trakcie budowy drzewa):** Drzewo Merkle'a iteruje po tabeli bez snapshot read loka. Węzeł zapisujący dane w trakcie budowy drzewa może wygenerować niespójny węzeł pośredni, co prowadzi do nieskończonej pętli synchronizacji (sync storm).
3. **Luka 3 (Naruszenie tie-breaku):** Wymiana gałęzi drzewa przyjmuje skrót większościowy bez weryfikacji pokolenia (`generation_check` z `fencing.py`), umożliwiając cofnięcie danych do starszej wersji.

Zadaniem agenta jest zrecenzowanie PR-a i dostarczenie pliku `review_findings.json` wskazującego powyższe błędy.

### 3.3 Dlaczego zadanie jest trudne
Wykrycie błędu brzegowego w hashowaniu oraz wyścigu bez blokady odczytu wymaga dogłębnej znajomości architektury shardingu Atlasa opisanej w `docs/schema-evolution.md` i `docs/incidents/INC-1203`.

### 3.4 Integracja z `auto_codex` i `agentic_knowledge`
* **`doc_context`:** Wstrzyknięcie historii incydentów synchronizacji (`INC-1201` .. `INC-1204`) oraz `docs/adr/ADR-0003`.
* **Tryb `review`:** Aktywacja modelu analitycznego przez router.
* **`recipe`:** Zapisywanie zasad weryfikacji granic hashy w bazie wiedzy.

### 3.5 Struktura katalogu i ewaluacja
```
datasets/code_review/atlas-antientropy-merkle-pr-review-001/
├── task.yaml
├── description.md
├── review_target/
│   ├── pr_merkle_opt.patch
│   └── pr_notes.md
├── public_tests/
│   └── test_review_schema_public.py
└── hidden_tests/
    ├── test_merkle_review_accuracy.py
    └── goldens/
        └── expected_merkle_findings.json
```
* **Kryterium sukcesu:**
  1. Wykrycie 3 luk w `review_findings.json`.
  2. Prawidłowe powiązanie Luki 3 z regułą fencing tokenów.

---

## 4. Plan wdrożenia i weryfikacji

1. Aktywacja kategorii w `descriptors/categories/code_review.yaml` (`category.enabled: true`).
2. Przygotowanie schematu JSON i walidatora raportu recenzji w `hidden_tests/`.
3. Weryfikacja CLI: `.venv/bin/akbench dataset validate --task tidewater-joint-consensus-pr-review-001`.
