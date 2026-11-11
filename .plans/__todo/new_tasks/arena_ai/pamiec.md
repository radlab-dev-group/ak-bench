# Mechanizm pamięci po stronie AK-Bench — jak to działa i jak mierzyć poprawnie

## 1. Podział ról: co robi AK-Bench, a co plugin

AK-Bench **nigdy nie dotyka treści wiedzy** — nie wie, co jest w bazie, nie czyta recept, nie indeksuje dokumentów. Operuje wyłącznie na **faktach o wiedzy**: kto może pisać, kto może czytać, czy baza jest gotowa, czy ramiona są porównywalne. Cała treść (zapis sesji, recepty, playbooki, indeksowanie, wstrzykiwanie kontekstu) dzieje się w pluginie `agentic_knowledge` wewnątrz routera. To rozgraniczenie jest fundamentem uczciwości pomiaru: AK-Bench gwarantuje *warunki*, plugin dostarcza *treść*, a ewaluacja mierzy *efekt*.

## 2. Faza planowania: `akbench knowledge plan`

`MemoryPlanBuilder` rozwija deskryptor w **plan pamięci** — i to jest moment, w którym eksperyment „albo staje się uczciwy, albo odrzuca". Plan nie uruchamia nic; buduje:

**Ramiona** (`MemoryArm`), każde ze stabilnym `arm_id`, trybem, zadaniem, digestem, dostępem do wiedzy, fingerprintem, pozycją i zależnością:

- `learning-<uid>` — tryb LEARNING, `knowledge_access = {read: learning.read_enabled, write: learning.write_enabled}`, pozycje 0..n,
- `replay-<scenario>` — tryb REPLAY, `knowledge_access = {read: True, write: False}`, z **bramą** (`gate`) i `depends_on = session_id` sesji learningu (kolejność logiczna: replay nie może wystartować przed learningiem),
- `fresh-<scenario>` — tryb FRESH, `knowledge_access = {read: False, write: False}`.

**Fingerprinty** — każde ramię niesie digest kanonicznego JSON-a faktów z listy `MEMORY_INVARIANTS`: `repository`, `commit`, `task`, `task_digest`, `evaluator`, `agent`, `agent_config`, `model`, `limits`, `sandbox_image`. Planista porównuje fingerprint replay i fresh **scenariusza** i odrzuca rozjazd, **nazywając klucz** (`invariant_differences`). To jest mechaniczna gwarancja, że para różni się wyłącznie dostępem do wiedzy — nie snapshotem repo, nie wersją zadania, nie modelem, nie limitami.

**Raport izolacji** (`IsolationReport`) — fakty, nie założenia: workspace per run, świeża sesja, czysty kontekst, izolowana historia agenta, izolowane cache lokalne — oraz `namespace_isolated`, który jest **własnością deploymentu**, nie eksperymentu: na managed instancji przestrzeń wiedzy jest własna (`SUPPORTED`), na external współdzielona (`UNSUPPORTED`, z powodem). Właściwość `comparable` = izolacja ramion **i** izolowana przestrzeń. Jeśli `comparable` jest fałsz, plan mówi to wprost, zamiast udawać porównywalność.

**Brama gotowości** (`ReplayGate`) — przed replayem probe pyta bazę o stan. Cztery statusy: `ready` (zapisy i indeksowanie potwierdzone), `not_ready`, `unverified`, `unsupported`. Brama blokuje replay, chyba że status to `ready` albo jawnie dopuszczono `allow_unverified` — wtedy run jest oznaczany `evidence_grade: unverified` (nigdy `verified`). Dodatkowa blokada: **sesja learningu, która nie wyprodukowała wiedzy, blokuje replay z własnego powodu** — replay na pustej bazie mierzyłby brak danych, nie efekt wiedzy.

## 3. Faza wykonania: `akbench experiment run`

Runner idzie po planie `tasks × variants × repetitions`, a dla eksperymentu pamięci dokłada trzy mechanizmy:

**a) Przypięcie workspace do scope pluginu.** Plugin grupuje kolekcje po basename katalogu roboczego. Runner AK-Bench nazywa checkout runa pamięci `<run slug>/<nazwa repo>` — slug unikalny per run (brak kolizji workspace), basename równy nazwie fixture (wszystkie ramiona tego samego fixture lądują w **jednej** kolekcji). Bez tego replay czytałby pustą kolekcję i eksperyment mierzyłby nic. Alternatywa operatora: tabela `scope.overrides` pluginu.

**b) Managed runtime per run.** Instancja routera startowana jest z `runtime_env` wariantu (pipeline pluginów), healthcheck, potem agent. Dostęp ramienia (`read`/`write`) przekłada się na flagi pluginu w tym procesie (`READ_ENABLED`/`WRITE_ENABLED`) — ramię fresh startuje z pluginem wiedzy **niezaładowanym w ogóle** (pipeline bez `agentic_knowledge`), więc nie może ani czytać, ani pisać, ani zanieczyścić kolekcji ramion on.

**c) Zwykły lifecycle runa** (orkiestrator): worktree pinned commit + mutacja zadania, prywatny agent home, sesja, ewaluacja, `run_record.json` z logiem przejść, fingerprintami workspace i werdyktem — wszystko zapisywane do historii pod tożsamością eksperymentu i wariantu.

## 4. Jak zapewnić, że baza MA playbooki, recepty i dokumenty w chwili pomiaru

Trzy źródła wiedzy, trzy różne mechanizmy gwarancji po stronie AK-Bench:

| Źródło | Jak trafia do bazy | Jak AK-Bench gwarantuje obecność w chwili pomiaru |
|---|---|---|
| **Dokumentacja operatora** | `DOCS_ENABLED` w managed instancji + dokumenty w repo; worker indeksuje asynchronicznie | readiness probe przed replayem: status musi być `ready` (writes + indexing settled); bez potwierdzenia replay jest zablokowany albo oznaczony `unverified` |
| **Recepty i playbooki z pracy** | ramię learning z `write_enabled: true`; plugin zapisuje archiwum sesji, compaction, dead-ends | brama blokuje replay, gdy sesja learningu „nie wyprodukowała wiedzy"; `depends_on` wymusza kolejność learning → replay |
| **Wiedza z poprzednich zadań** | wiele zadań w `learning.tasks` (każde dokłada do tej samej kolekcji przez scope) | ten sam scope (basename fixture) + ta sama przestrzeń nazw (managed) |

Kluczowe zdanie z kodu bramy: *„replay na pustej bazie mierzy brak danych, nie efekt wiedzy"* — dlatego pusta sesja learningu to blokada, nie cichy null.

## 5. Jak poprawnie mierzyć

1. **Porównanie to zawsze para replay vs fresh tego samego scenariusza** — identyczne fingerprinty, różnica tylko w `knowledge_access`. Efekt = `delta_success = success_replay − success_fresh`.
2. **Evidence grade każdego replaya**: `verified` (readiness potwierdzona) / `unverified` (`allow_unverified`) / `not_run` (zablokowany). Do raportu wchodzą tylko `verified`; `unverified` jest oznaczony i nie udaje dowodu.
3. **Retrieval ≠ utilization**: że plugin pobrał wiedzę, nie znaczy, że agent jej użył. Obie metryki są dziś `unavailable` (router nie eksportuje liczników) — raportuje się je jako `unavailable` z powodem, **nigdy jako zero**.
4. **Baseline w raporcie** — wariant bez pamięci; wszystkie porównania względem niego.
5. **Na external routerze nie mierz pamięci**: readiness to `unsupported`, przestrzeń współdzielona, `comparable: false`. Albo managed lifecycle, albo jawne `allow_unverified` ze świadomością, że wynik jest nie-dowodowy.

## 6. Praktyczna recepta dla dataset_001

```
1. Managed router (własna przestrzeń wiedzy per eksperyment)
2. DOCS_ENABLED=on + dokumentacja w docs/  →  zasiew dokumentów
3. knowledge plan: ramiona + fingerprinty + brama + izolacja
   (odrzut, jeśli replay/fresh różnią się czymś poza wiedzą)
4. knowledge readiness: status ready dla zasianych dokumentów
5. experiment run: learning (write) → readiness gate → replay (read) + fresh (none)
6. Raport: delta replay−fresh, tylko evidence_grade=verified
```

Chcesz, żebym taki eksperyment przygotował jako gotowy plik (z dokumentacją zasianą przez `DOCS_ENABLED` i scenariuszami na zadaniach dataset_001)?




------------

------------

------------

------------

Dobre pytanie — sprawdzę w kodzie CLI, czy `experiment run` dla typu `knowledge_replay` sam rozwija ramiona pamięci (learning → replay → fresh), czy learning trzeba uruchomić osobno.

# Krok po kroku: jak zmierzyć wpływ pamięci

Krótka odpowiedź na Twoje pytanie: **nie, learning nie jest osobnym krokiem, który uruchamiasz ręcznie — ale `experiment run` też nie wykonuje ramion pamięci**. I to rozróżnienie jest kluczowe, bo w AK-Bench istnieją dziś **dwie różne ścieżki** pomiaru pamięci, z których tylko jedna działa end-to-end.

## Co robi każdy krok CLI (i czego nie robi)

| Krok | Co robi | Czego NIE robi |
|---|---|---|
| `akbench knowledge plan FILE` | Buduje i waliduje **plan pamięci**: ramiona learning/replay/fresh, fingerprinty, bramę readiness, raport izolacji | **Nie uruchamia nic** — to inspekcja |
| `akbench knowledge readiness` | Pyta deployment, co potrafi powiedzieć o bazie wiedzy | Nie czeka, nie naprawia |
| `akbench experiment run FILE` | Wykonuje macierz `tasks × variants × repetitions` przez orkiestrator | **Nie wykonuje ramion pamięci** — nie aplikuje per-arm flag read/write |
| `akbench run single <task>` | Jeden run: prepare → execute → evaluate → record | Bez wiedzy (chyba że sam dasz runtime_env) |

Sprawdziłem w kodzie: `MemoryPlanBuilder` (ramiona, fingerprinty, brama) jest używany **wyłącznie** przez `akbench knowledge plan`. Runner `experiment run` dla eksperymentu `knowledge_replay` robi tylko jedną rzecz specyficzną dla wiedzy: **przypina workspace** (`<run slug>/<nazwa repo>`, żeby scope pluginu się zgadzał). Aplikowania flag read/write per ramię w runnerze **nie ma** — `docs/KNOWLEDGE_REPLAY.md` mówi wprost, pod „What is deliberately not here yet": *„The plan does not run the arms: scheduling learning, replay and fresh runs is the work of the storage and reporting phases."*

## Ścieżka A — działa dziś end-to-end: `configuration` + czynnik `knowledge_enabled`

To jest pomiar „model vs model + baza wiedzy" w **tej samej sesji** (wiedza pomaga w trakcie pracy, nie przez sesje learning/replay). Wzorce: `knowledge-on-off.yaml`, `full-matrix.yaml`.

Kroki:

1. **Napisz eksperyment** typu `configuration`, `mode: router`, `lifecycle: managed`, z czynnikiem `knowledge_enabled` i `custom_matrix` (4 ramiona: model A ± wiedza, auto_codex ± wiedza — jak w moim pliku `model-a-vs-autocodex-knowledge.yaml`).
2. **Walidacja i plan:** `akbench experiment validate FILE` → `akbench experiment plan FILE --variants --json` (sprawdź `tasks × variants × repetitions` i koszt).
3. **Uruchomienie:** `akbench experiment run FILE --store` — runner dla każdego wariantu startuje managed instancję z jego `runtime_env` (pipeline pluginów) i aplikuje `knowledge_enabled` przez `factor_env` (`LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED`). Ramię off startuje **bez pluginu wiedzy w procesie** — nie czyta, nie pisze, nie zanieczyszcza.
4. **Wyniki:** `akbench report all` / `akbench export experiment` — porównania względem baseline (model A bez wiedzy).

W tej ścieżce **nie ma osobnego learningu** — wiedza (dokumenty przez `DOCS_ENABLED`, ewentualnie zapis z bieżących sesji przez `WRITE_ENABLED`) jest dostępna od startu każdego runa z włączonym pluginem. Zasiew dokumentacji = dokumenty w repo + `DOCS_ENABLED` w instancji + readiness przed pomiarem.

## Ścieżka B — planowanie gotowe, wykonanie ramion nie: `knowledge_replay`

To jest pomiar „najpierw agent się uczy (learning), potem pracuje na bazie w nowej sesji (replay) vs bez bazy (fresh)".

Kroki dziś:

1. **Napisz eksperyment** typu `knowledge_replay` z blokiem `knowledge` (learning.tasks, scenarios, fresh_control).
2. **`akbench knowledge plan FILE`** — buduje ramiona, sprawdza fingerprinty replay/fresh, bramę, izolację. To jest moment, w którym eksperyment „staje się uczciwy albo odpada".
3. **`akbench knowledge readiness`** — co deployment powie o bazie (na external routerze: `unsupported` → brama zablokuje).
4. **`akbench experiment run FILE --store`** — uruchamia runy macierzy z przypiętym workspace. **Ale**: runner nie rozróżnia ramion learning/replay/fresh ani nie aplikuje ich flag read/write. Pełna orkiestracja learning → readiness → replay **nie jest jeszcze zaimplementowana** w CLI.

Czyli: ścieżka B jest dziś **planowalna i walidowalna, ale nie wykonywalna end-to-end jedną komendą**. Learning jako osobny krok nie istnieje — nie ma komendy „uruchom learning". Gdybyś chciał dziś zmierzyć learning→replay, musiałbyś orkiestrować ręcznie (run learning z włączonym zapisem, czekanie na readiness, run replay z odczytem) — a to jest dokładnie ten brakujący kawałek runnera.

## Podsumowanie decyzji

- Chcesz **„model vs model + KB"** (wiedza dostępna w trakcie pracy) → **ścieżka A**, działa w pełni przez `experiment run`.
- Chcesz **„agent najpierw się uczy, potem pracuje na bazie"** (pamięć między sesjami) → **ścieżka B**: planowanie i walidacja działają (`knowledge plan`), ale wykonanie ramion to dziś luka — albo poczekać na runner, albo orkiestrować ręcznie.

Którą ścieżkę chcesz realizować na dataset_001? Mogę przygotować gotowy plik dla ścieżki A (z zasiewem dokumentacji) albo dla ścieżki B (z pełnym planem pamięci do inspekcji).



--------------

--------------

--------------

--------------


To jest dokładnie scenariusz learning → replay. Sprawdzę, jak dziś — ręcznie, poza runnerem eksperymentu — można przeprowadzić run learningu z zapisem i run replay z odczytem na tej samej bazie: jak ustawić flagi wiedzy, przestrzeń nazw i scope.

# Jak dziś przeprowadzić learning → replay ręcznie (krok po kroku)

Krótka odpowiedź: **learning nie jest osobną komendą, ale da się go przeprowadzić ręcznie** — jako trzy zwykłe runy (`run single`) z różnymi flagami wiedzy, na tej samej przestrzeni nazw. Runner eksperymentu tego nie zorkiestruje za Ciebie (ramiona pamięci to dziś tylko planowanie), więc orkiestrujesz sam. Oto cała procedura.

## Zanim zaczniesz: trzy fakty o bazie wiedzy

1. **Baza wiedzy nie żyje w instancji routera, tylko w Redis pluginu** (`LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_*`). Managed instancja startuje i umiera per run, ale Redis persistuje — dlatego learning z jednej instancji jest czytelny dla replay z drugiej. Bez Redis plugin „ładuje się i nic nie robi" (stateless).
2. **Przestrzeń nazw = `LLM_ROUTER_KNOWLEDGE_AGENTIC_COLLECTION_PREFIX`.** Ten sam prefix w learningu i replayu = ta sama baza. Inny prefix = inna baza. To jest Twój „identyfikator eksperymentu wiedzy".
3. **Scope kolekcji = basename katalogu roboczego.** I tu jest pułapka ręcznych runów (rozdz. 5).

## Krok 1 — run learningu (agent pracuje, baza się zapełnia)

```bash
export LLM_ROUTER_UTILS_PLUGINS_PIPELINE=agentic_knowledge
export LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED=true
export LLM_ROUTER_KNOWLEDGE_AGENTIC_WRITE_ENABLED=true
export LLM_ROUTER_KNOWLEDGE_AGENTIC_READ_ENABLED=true
export LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_ENABLED=true   # + indeksowanie dokumentacji repo
export LLM_ROUTER_KNOWLEDGE_AGENTIC_COLLECTION_PREFIX=dataset001-exp

akbench run single <learning-task> --agent codex \
  --mode router --runtime llm-router-ak-bench --store
```

Co się dzieje: managed instancja startuje z Twoim środowiskiem (zmienne operatora przechodzą do procesu — `process_environment()` = ambient + deskryptor + czynniki + runtime_env). Agent pracuje zadanie; plugin zapisuje archiwum sesji, recepty, playbooki, dead-ends; worker indeksuje asynchronicznie. Dokumentacja z repo trafia do rejestru dokumentów przez `DOCS_ENABLED`.

## Krok 2 — poczekaj na indeksowanie (readiness ręcznie)

Probe w AK-Bench to dziś tylko `NoReadbackProbe` → status `unsupported`. Czyli **potwierdzenie gotowości jest Twoim zadaniem**: poczekaj (zmierzony lag to minuty, nie sekundy) i zweryfikuj w `router.log` z artefaktów runa, że zapisy i indeksowanie się zakończyły. Replay startujący za wcześnie mierzy nieistniejącą bazę i da fałszywy efekt zerowy.

## Krok 3 — run replayu (nowa sesja, ta sama baza, tylko odczyt)

```bash
export LLM_ROUTER_KNOWLEDGE_AGENTIC_WRITE_ENABLED=false   # replay nigdy nie pisze
export LLM_ROUTER_KNOWLEDGE_AGENTIC_READ_ENABLED=true
# COLLECTION_PREFIX bez zmian: dataset001-exp

akbench run single <replay-task> --agent codex \
  --mode router --runtime llm-router-ak-bench --store
```

Nowy workspace, nowa sesja, czysty kontekst — agent widzi tylko repo + wstrzyknięty blok `<agentic_knowledge>`. Weryfikacja, że baza faktycznie działa: blok jest widoczny w kontekście/rollout replayu, a `router.log` pokazuje pobranie.

## Krok 4 — run fresh (kontrola, zero wiedzy)

```bash
export LLM_ROUTER_UTILS_PLUGINS_PIPELINE=agentic_routing_codex  # bez agentic_knowledge
# albo: LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED=false

akbench run single <replay-task> --agent codex \
  --mode router --runtime llm-router-ak-bench --store
```

Identyczne zadanie, model, limity — różnica wyłącznie w wiedzy.

## Krok 5 — porównanie

```bash
akbench history        # runy z werdyktami
akbench report all     # delta replay − fresh względem baseline
```

Efekt pamięci = `task_success_rate(replay) − task_success_rate(fresh)`. Pamiętaj: retrieval ≠ utilization — że plugin pobrał wiedzę, nie znaczy, że agent jej użył; metryki wiedzy są `unavailable`, więc dowodem jest różnica wyników + ślad w logach, nie liczniki.

## Pułapki, które musisz obsłużyć ręcznie

1. **Scope basename (największa).** `run single` tworzy workspace o unikalnej nazwie per run → plugin grupuje kolekcje po basename → learning i replay trafią do **różnych kolekcji** i replay zobaczy pustkę. Rozwiązanie: tabela `scope.overrides` w konfiguracji pluginu (mapuje deklarowaną ścieżkę na wspólny klucz scope) — to jest udokumentowana droga operatora dla checkoutów, których harness nie nazywa. (W `experiment run` harness przypina basename sam — dlatego tam problem nie występuje.)
2. **Prefix musi być identyczny** we wszystkich trzech runach; zmiana prefixu = nowa, pusta baza.
3. **Replay z włączonym zapisem** zanieczyściłby bazę własnym wynikiem — zawsze `WRITE_ENABLED=false` w replayu.
4. **Fresh z pluginem załadowanym** (nawet wyłączonym flagą) to nie to samo co fresh bez pluginu — czysta kontrola to brak `agentic_knowledge` w pipeline.
5. **Kolejność**: learning musi się zakończyć (i zindeksować) przed replayem — runner tego nie wymusi, pilnujesz sam.

Chcesz, żebym przygotował gotowy skrypt orkiestrujący te trzy runy (learning → wait/readiness → replay → fresh) z ustawionymi env i weryfikacją scope/prefixu przed startem?