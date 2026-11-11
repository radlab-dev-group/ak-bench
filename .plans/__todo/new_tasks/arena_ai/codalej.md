Dobre pytanie — sprawdzę najpierw, co mówi plan implementacyjny repo, żeby propozycje były osadzone w jego roadmapie, a nie wyjęte z powietrza.

Po sprawdzeniu planu (`8.1 Kategorie` — dokładnie te 7, które właśnie wypełniliśmy) i rozkładu trudności w 72 zadaniach, oto moje propozycje — od najpilniejszych:

## 1. Push brancha (operacyjnie najpilniejsze)
Commit `78437fb` jest tylko lokalny — klon nie ma remote `origin`, więc nie mogę go wypchnąć. Musisz dodać remote i zrobić `git push origin feat/new_task` (albo daj mi URL remote'a, to przygotuję komendy). Bez tego cała praca nie trafi do repo.

## 2. Kalibracja pilotem (najwyższa wartość merytoryczna)
Trudności są dziś etykietami z głowy. Proponuję mały eksperyment kalibracyjny: silny i słaby agent na próbce ~12 nowych zadań (po 1–2 z każdej kategorii), i sprawdzenie, czy pass rate układa się easy > medium > hard > expert. Repo ma `configs/experiments/` — mogę przygotować config i przeanalizować wyniki wg metryk z sekcji 18 planu (success rate, regression rate). Jeśli np. `debugging/hard` okaże się trywialne, lepiej to wiedzieć teraz niż po publikacji.

## 3. Wzmocnienie ewaluacji `code_review` (znana słabość)
Obecny hidden test sprawdza słowa-klucze w `REVIEW.md` — agent może „wygrać" pisząc review napakowane słowami bez realnej analizy. Opcje: sędzia LLM jako evaluator, wymóg referencji `plik:linia` dla każdego findinga, albo penalizacja fałszywych findingów. To najsłabszy punkt nowej 40-stki.

## 4. Domknięcie luk w macierzy trudności
Aktualny rozkład pokazuje wyraźne dziury:

| | easy | medium | hard | expert |
|---|---|---|---|---|
| debugging / refactoring / testing / code_review | 2 | 2 | 2 | **0** |
| architecture / security / performance | **0** | 2–3 | 2 | 1–2 |

Wymaga to zmiany deskryptorów (dopuszczenie `expert` w 4 kategoriach, `easy` w 3) + nowych zadań, np. debugging-expert z defektem wielomodułowym o mylących objawach, security-easy z prostą walidacją wejścia. Świadomie tego nie ruszałem, bo prosiłeś o bieżące limity — ale to naturalny kolejny batch.

## 5. Drobiazgi
- Odznaczenie `8.1` jako zrealizowanego w `.plans/AK-Bench-implementation-plan.md`
- Sprawdzenie, czy CI repo przechodzi na nowych testach

**Moja rekomendacja kolejności:** 1 → 2 → 3, a 4 jako osobna decyzja (czy poszerzamy deskryptory). Które z nich mam ruszyć?