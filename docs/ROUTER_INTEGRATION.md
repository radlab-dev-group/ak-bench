# Integracja z LLM Router — wyniki spiku (Faza 0)

Dotyczy instancji LLM Router, przez którą uruchamiane były runy spiku.
Opisuje tylko to, co zostało sprawdzone w żądaniach HTTP albo w kodzie repozytorium
`/mnt/data2/dev/develop/llm-router` i `/mnt/data2/dev/develop/llm-router-plugins`.

## 0. Badana instancja

| Element | Wartość |
|---|---|
| Adres | `http://192.168.100.65:8081` |
| Tryb życia instancji | **external** — instancja współdzielona, niezarządzana przez AK-Bench |
| Autoryzacja | klucz w `Authorization: Bearer $LLM_ROUTER_API_KEY` |
| Endpointy agentowe | `POST /v1/responses` (Codex, `wire_api = "responses"`), `POST /v1/chat/completions` |
| Kod routera | `llm-router` (`llm_router_api`), pluginy: `llm-router-plugins` |

## 1. Healthcheck — verified

| Metoda i ścieżka | Odpowiedź |
|---|---|
| `GET /health` | `200`, ciało `{"body":"healthy","status":true,"stream":false}` |
| `GET /healthz` | `403` — odmowa polityki dostępu |
| `GET /health/live` | `403` — odmowa polityki dostępu |

Do healthchecku benchmaku nadaje się wyłącznie `GET /health`.

## 2. Inwentarz modeli — verified

`GET /v1/models` (kod `200`) zwraca 6 modeli:

```text
google/gemma-4-12b-it
google/gemini-3.1-flash-lite-preview
google/gemma-4-12b-it-playground
qwen3-coder:30b
qwen/Qwen3.8-27B
qwen/Qwen3.8-Flash-Next
```

Uwaga: `auto_codex` **nie pojawia się** na tej liście, mimo że działa jako alias
w zapytaniach. Lista `/v1/models` nie jest więc pełnym obrazem przestrzeni
wymiaru „model".

## 3. Czy da się odczytać konfigurację efektywną? — NIE przez HTTP

Sprawdzone i odrzucone (`403 Access to this endpoint is denied by policy`):

`/config`, `/admin/config`, `/routing/config`, `/knowledge/stats`, `/utils`,
`/version`, `/api_version`, `/v1/api_version`, `/list_models`.

Konfiguracja efektywna jest dostępna wyłącznie z poziomu hosta routera:

- plik modeli: `LLM_ROUTER_MODELS_CONFIG` (domyślnie `resources/configs/models-config.json`),
  wymagany klucz `active_models`,
- konfiguracja pluginów: pliki `llm_router_plugins/resources/<typ>/<plugin>.json`
  plus nadpisania środowiskowe.

Wniosek: w trybie `external` AK-Bench **nie jest w stanie zweryfikować**
konfiguracji efektywnej routera ani pluginów. Zgodnie z zasadą planu
(„konfiguracja nie jest uznawana za aktywną bez weryfikacji") eksperymenty na
współdzielonym routerze muszą być oznaczane `unverified`, chyba że zapewniony
jest odczyt plików/logeów z hosta.

## 4. Pipeline pluginów — verified z kodu

| Element | Wartość |
|---|---|
| Zmiennej aktywującej pipeline | `LLM_ROUTER_UTILS_PLUGINS_PIPELINE`, np. `"agentic_routing_codex,agentic_knowledge"` |
| Rejestr | `llm_router_plugins.utils.registry.MAIN_UTILS_REGISTRY` |
| Model życia pluginu | instancja na proces, `apply(payload)` przed guardrails i przed wyborem providera |
| Kolejność | plugin, który pierwszy nadpisze `model`, wygrywa dispatch; `agentic_knowledge` musi być **po** routingu |

## 5. Wymiar „Auto Codex" (plugin `agentic_routing_codex`)

- Wyzwalacz: model-alias `auto_codex` z providerem `api_type: "builtin"`.
- Prefiks ENV: `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_`
  (w tym `…TRIGGER`, `…HEURISTIC_ENABLED`, `…SEMANTIC_ENABLED`).
  Nazwy potwierdzone w kodzie: `AGENTIC_ROUTING_PREFIX = "LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_"`,
  a prefiks Codexa to `AGENTIC_CODEX_ROUTING_PREFIX = f"{AGENTIC_ROUTING_PREFIX}CODEX_"`.
- Dowód działania **verified**: zapytanie `model: "auto_codex"` zakończyło się
  odpowiedzią `"model": "qwen/Qwen3.8-Flash-Next"` — routing podmienił model.

## 6. Wymiar „Knowledge" (plugin `agentic_knowledge`)

| Element | Wartość |
|---|---|
| Klucz rejestru | `agentic_knowledge` |
| Klasa | `llm_router_plugins.utils.knowledge.agentic_knowledge.plugin.AgenticKnowledgePlugin` |
| Prefiks ENV | `LLM_ROUTER_KNOWLEDGE_AGENTIC_` (potwierdzony w `config.py`) |
| Flagi ENV (verified z kodu) | `ENABLED`, `READ_ENABLED`, `WRITE_ENABLED`, `ESCALATION_ENABLED`, `ARCHIVE_ENABLED`, `DOCS_ENABLED`, `DOCS_CONTEXT_ENABLED` |
| Domyślna konfiguracja | `llm_router_plugins/resources/knowledge/agentic_knowledge.json` |
| Worker indeksujący | `llm-router-agentic-kb-worker` |
| Zależności | klient SSE (`sse_lib`) + Redis; brak zależności = plugin się ładuje i nic nie robi |
| Polityka błędów | fail-open dla ruchu, fail-hard dla nieprawidłowej polityki (start) |

Fakty ważne dla eksperymentów Knowledge/Replay:
- plugin zmienia `payload["model"]` tylko gdy zadziała eskalacja, oraz dokłada
  blok kontekstu; adnotacja ląduje w `routing.knowledge` **w wewnętrznym payloadzie**,
  nie w odpowiedzi HTTP widocznej dla agenta;
- koniec sesji agenta **nie jest** dowodem gotowości KB — indeksacja jest
  asynchroniczna (worker), więc Replay wymaga wcześniejszego potwierdzenia
  zakończenia zapisu i indeksowania;
- realny ślad działania wiedzy: wstrzykiwany blok `<agentic_knowledge>` był
  widoczny w kontekście bieżącej sesji operatorskiej w tym repo (dowód
  anegdotyczny, ale z prawdziwego ruchu).

## 7. Metryki i sygnaly aktywności pluginów — istotna luka

`GET /metrics` (kod `200`, Prometheus) zawiera m.in.:

```text
http_requests_total, http_request_duration_seconds_*, http_request_size_bytes_*
http_request_exceptions_total, http_requests_in_progress
llm_router_provider_calls_total, llm_router_provider_error_total
llm_router_provider_latency_seconds_*, llm_router_model_fallback_total
llm_router_lb_strategy_selected_total, llm_router_retry_total
llm_router_tokens_total, llm_router_response_format_total
llm_router_pipeline_stage_total{result="success",stage="provider_resolved"}
guardrail_incidents_total, masker_incidents_total
```

- `llm_router_pipeline_stage_total` ma **tylko** stage `provider_resolved`.
- Brak liczników per plugin: ani `knowledge_retrieval_count`, ani
  `knowledge_write_count`, ani sygnałów `agentic_routing_codex`.

Wniosek: obecny zestaw metryk nie wystarcza do zmierzenia wymiarów Knowledge
i Auto Codex. Potrzebne jest jedno z:
1. włączenie logów routera (`LLM_ROUTER_LOG_TO_FILE`, `LLM_ROUTER_LOG_LEVEL`)
   i parsowanie linii decyzyjnych pluginów,
2. własny eksport pluginów do `/metrics`,
3. odczyt stanu KB/SSE bezpośrednio.

Do czasu zapewnienia jednego z nich metryki wiedzy muszą być raportowane
jako `unavailable`, a nie jako zero.

**Zmierzona obserwacja opóźnienia indeksacji (2026-10-30):** w trakcie pracy nad
tym repo wstrzykiwany rejestr dokumentów obejmował wyłącznie `README.md` i plik
planu, mimo że dwa nowe pliki `docs/*.md` istniały już na dysku od kilku minut.
Potwierdza to tezę z planu: **gotowość KB trzeba weryfikować osobno**, a okno
między zapisem a dostępnością wiedzy jest mierzalną metryką (`indexing_latency`).

## 8. Zmienne środowiskowe uruchomienia routera (verified z `docs/ENV_DEFINITIONS.md`)

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `LLM_ROUTER_MODELS_CONFIG` | `resources/configs/models-config.json` | plik konfiguracji modeli |
| `LLM_ROUTER_LOG_FILENAME` | `llm-router.log` | nazwa pliku logu |
| `LLM_ROUTER_LOG_LEVEL` | `INFO` | poziom logowania |
| `LLM_ROUTER_LOG_TO_FILE` | `false` | zapis logów do pliku |
| `LLM_ROUTER_LOG_MAX_BYTES` | `52428800` | rotacja logów |
| `LLM_ROUTER_LOG_BACKUP_COUNT` | `5` | liczba kopii rotacji |
| `LLM_ROUTER_MINIMUM` | `False` | tryb proxy-only |
| `LLM_ROUTER_IN_DEBUG` | `False` | tryb debug (wymusza DEBUG) |
| `LLM_ROUTER_VERBOSE` | `False` | logowanie surowych, **niezamaskowanych** zapytań (PII!) |
| `LLM_ROUTER_AUTH_ENABLED` | `false` | wymuszanie autoryzacji kluczkami `sk-llmr-live-` |

`LLM_ROUTER_VERBOSE` jest jedynym sprawdzonym sposobem zobaczenia pełnych
payloadów (a więc i adnotacji `routing.knowledge`), ale loguje PII — dla
benchmaku dopuszczalny wyłącznie w izolowanym środowisku i z filtracją sekretów.

## 9. Tryb zarządzany a współdzielony — decyzja projektowa

| Cecha | `external` (obecny) | `managed` (docelowy dla eksperymentów) |
|---|---|---|
| Sterowanie ENV pluginów per run | niemożliwe | pełne |
| Odczyt konfiguracji efektywnej | niemożliwy (403) | możliwy (plik + logi) |
| Izolacja stanu KB | brak | możliwa (osobny Redis/SSE) |
| Ryzyko zmian w trakcie runu | realne | wyeliminowane |
| Powtarzalność | ograniczona | wymog planu |

**Rekomendacja:** eksperymenty z wymiarami Knowledge i Auto Codex wymagają
instancji `managed` (własny kontener + własny Redis/SSE + własny plik
konfiguracji). Współdzielony router nadaje się do integracji i testów
smoke, ale jego wyniki muszą być oznaczane `valid_with_warnings` lub
`invalid` w zależności od wymaganych capabilities.

## 10. Status integracji

| Zdolność | Status |
|---|---|
| Healthcheck | verified |
| Inwentarz modeli (`/v1/models`) | verified |
| Wywołanie `chat/completions` przez alias `auto_codex` | verified |
| Routing agenticzny podmienia model | verified (odpowiedź `model`) |
| Wywołanie `/v1/responses` i obserwacja modelu w odpowiedzi | unverified |
| Odczyt konfiguracji efektywnej przez HTTP | unsupported |
| Metryki per plugin | unsupported |
| Start/stop instancji przez AK-Bench | unverified (nie implementowane w Fazie 0) |
| Sterowanie pluginami ENV per run | unverified (wymaga `managed`) |
| Gotowość KB (koniec indeksacji) | unverified |
| Nowa sesja po stronie routera | unverified (router bezstanowy dla ruchu) |
