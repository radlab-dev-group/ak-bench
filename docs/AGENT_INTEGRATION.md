# Integracja z agentem — wyniki spiku (Faza 0)

Dokument opisuje **wyłącznie fakty zweryfikowane lokalnie**. Każda capability ma
status `verified`, `partial`, `unsupported` lub `unverified`. Nie ma tu domysłów.

## 0. Warunki weryfikacji

| Element | Wartość |
|---|---|
| Agent | Codex CLI `0.166.0` (`codex-cli 0.166.0`), instalacja standalone |
| Ścieżka binarki | `~/.local/bin/codex` → `~/.codex/packages/standalone/releases/0.166.0-x86_64-unknown-linux-musl/bin/codex` |
| System | Ubuntu 22.04, jądro x86_64 |
| Provider / runtime | LLM Router `http://192.168.100.65:8081/v1`, `wire_api = "responses"` |
| Model (requested) | `auto_codex` (alias wyzwalacz routingu agenticznego) |
| Data weryfikacji | 2026-10-30 |
| Prototyp | `spike/run_spike.py`, wynik `data/artifacts/spike/spike-20261030-130140/` |

Wynik prototypu: status `completed`, ewaluacja `1 passed`, czas 96.7 s,
`input_tokens=39313` (`cached_input_tokens=21010`), `output_tokens=588`,
6 wywołań narzędzia `exec_command`, sesja `01a18cb0-474a-7da3-9adf-3ae6967c6d69`.

## 1. Uruchamianie agenta

Tryb nieinteraktywny (jeden proces = jedno zadanie):

```bash
codex exec [OPTIONS] [PROMPT]
```

- Brak repozytorium Git jest błędem — `--skip-git-repo-check` wyłącza sprawdzanie.
- Kod wyjścia: `0` przy poprawnym zakończeniu; błąd agenta i błąd infrastruktury
  **trzeba rozdzielać po strumieniu JSONL i stderr**, nie po kodzie wyjścia.
- `codex doctor` potwierdza stan instalacji, autoryzacji i baz CODEX_HOME.

## 2. Przekazanie zadania

| Sposób | Status | Uwagi |
|---|---|---|
| Argument `PROMPT` | verified | użyte w spiku |
| `stdin` (lub `-`) | verified (dokumentacja CLI) | przy jednoczesnym argumencie stdin jest dokładany jako blok `<stdin>` |
| `--output-schema <PLIK>` | verified (dokumentacja) | wymusza odpowiedź finalną zgodną z JSON Schema |
| `-o, --output-last-message <PLIK>` | verified | zapis wiadomości końcowej; użyte w spiku |

## 3. Wskazanie workspace

- `-C, --cd <DIR>` — katalog roboczy agenta. **verified** (użyty w spiku).
- `--worktree` — zarzadzane przez Codex drzewo pracy Git. `unverified` (nie testowane;
  AK-Bench ma własny Workspace Manager, patrz wniosek w §12).
- `--add-dir <DIR>` — dodatkowe katalogi do zapisu. `verified` (istnieje w CLI),
  semantyka `unverified`.

## 4. Parametryzacja

| Parametr | Status | Uwagi |
|---|---|---|
| `-m, --model <MODEL>` | verified | podanie `auto_codex` jest poprawne |
| `-c, --config key=value` | verified | nadpisanie TOML, ścieżki kroplowe, np. `-c approval_policy="never"` |
| `-p, --profile <NAME>` | verified (CLI) | warstwa `~/.codex/<name>.config.toml` |
| `--enable/--disable <FEATURE>` | verified (CLI) | skrót do `-c features.<name>=…` |
| `--strict-config` | unverified | nietestowane pod kątem twardego failu |
| `--ignore-user-config` | verified | używane pośrednio przez izolowany `CODEX_HOME` |
| `--ignore-rules` | unverified | nie testowane |

## 5. Sesje i izolacja kontekstu

- Każde wywołanie `codex exec` tworzy nowa nitke/seesję — identyfikator
  w zdarzeniu `thread.started.thread_id`. **verified**.
- Wymuszenie nowej sesji = nowe wywołanie procesu bez `resume`. **verified**.
- `codex exec resume <SESSION_ID>` / `resume --last` — kontynuacja kontekstu. **verified (CLI)**.
- `codex exec fork` — nowa sesja na bazie istniejącej. **verified (CLI)**.
- `--ephemeral` — bez zapisu sesji na dysk. **verified (CLI)**;
  uwaga: wyłącza wtedy źródło trace'u z rollouta (§8).
- Resetu istniejącej sesji nie ma — jest tylko resume/fork → `session_reset: unsupported`.

### 5.1. Izolowany `CODEX_HOME`

Sprawdzone: ustawienie `CODEX_HOME` na pusty katalog wystarcza do uruchomienia
agenta **bez logowania**, o ile provider konfigurowany jest przez `env_key`.
W spiku katalog zawierał wyłącznie `config.toml` z providerem i `env_key = "LLM_ROUTER_API_KEY"`.

Wnioski dla AK-Bench:
- `fresh_agent_session` i `clean_agent_context` realizuje się przez
  osobny proces + osobny `CODEX_HOME` na run;
- w `CODEX_HOME` powstają też bazy (`state_*.sqlite`, `logs_*.sqlite`,
  `thread_history_*.sqlite`), więc izolacja pamięci agenta wymaga izolacji całego katalogu;
- wpisów `[projects."…"] trust_level` nie trzeba tworzyć — przy
  `approval_policy="never"` i `sandbox_mode="workspace-write"` zadanie wystartowało
  bez ufności katalogu. **verified**

## 6. Wykrywanie zakończenia i status

Strumień `codex exec --json` (JSONL, zdarzenia płaskie — pole `type` na górnej warstwie):

| Zdarzenie | Znaczenie |
|---|---|
| `thread.started` | identyfikator sesji |
| `turn.started` | początek tury |
| `turn.completed` | sukces tury, zawiera `usage` |
| `turn.failed` | porażka tury, zawiera `error` |
| `item.started` / `item.updated` / `item.completed` | pozycje (patrz §8) |
| `error` | błąd nieodwracalny strumienia |

Typy pozycji: `agent_message`, `reasoning`, `command_execution`, `file_change`,
`mcp_tool_call`, `web_search`, `todo_list`.

- Wykrywanie zakończenia: `turn.completed` / `turn.failed` + zakończenie procesu. **verified**
- Odczyt statusu procesu działającego: **brak zewnętrznego API** — tylko strumień.
  `status_query: partial`
- Dostępne są też `codex app-server` / `agents` / `queue` (sterowanie sesjami przez
  daemon), ale dla benchmarku **unverified** — nie było potrzeby użycia.

## 7. Timeout i anulowanie

- Brak flagi timeoutu w CLI. **verified (brak)**.
- Zastosowane podejście: `SIGINT` na proces z alarmem (w prototypie),
  następnie `wait()`. Ścieżka timeoutu **nie została pokryta** na żywo
  (run zakończył się przed limitem) → `cancellation: partial`.
- `SIGKILL` zabija drzewo procesu — mechanizm trywialny, ale pozostawia
  niedomknięty rollout; przy ponownych próbach wymaga oznaczenia runu
  jako `infrastructure_error`, nie `agent_error`.

## 8. Trace'y, narzędzia, obserwacje

Dwa niezależne źródła:

1. **Strumień JSONL** (`--json`): bieżące pozycje, w tym `command_execution`
   z `command`, `aggregated_output`, `exit_code`, `status`.
2. **Rollout sesji**: `CODEX_HOME/sessions/RRRR/MM/DD/rollout-<czas>-<uuid>.jsonl`.

W rolloutie (wpisy `type` + `payload`):

| Wpis | Zawartość | Wykorzystanie w AK-Bench |
|---|---|---|
| `session_meta` | `session_id`, `cwd`, `cli_version`, `model_provider`, `originator`, `base_instructions` | wersja agenta,_observed cwd, provider |
| `turn_context` | `model`, `cwd`, `approval_policy`, `sandbox_policy`, `permission_profile` | **konfiguracja obserwowana** |
| `response_item/function_call` | `name`, `arguments`, `call_id`, `status` | tool trace |
| `response_item/function_call_output` | wynik narzędzia | korelacja narzędzie → efekt |
| `response_item/message`, `/reasoning` | treść agenta, rozumowanie | analiza jakościowa |
| `token_usage_record` | `usage`, `turn_token_usage`, `thread_token_usage` (skumulowane) | tokeny |
| `world_state` | stan świata | diagnostyka |

W spiku: 6 × `exec_command`, tokeny wzięte z `thread_token_usage`
(pole `total_tokens` jest sumą z `input`/`output`).
`tool_trace: verified`.

## 9. Tokeny i koszt

- Token usage: `verified`. Klucze `usage`: `input_tokens`, `cached_input_tokens`,
  `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`, `total_tokens`.
- **Koszt: `unsupported`** — ani strumień, ani rollout nie zawierają żadnych pól
  kosztowych (brak wystąpienia `cost*` w całym rolloutie), a router nie ufa
  cenniku per run. AK-Bench musi raportować `total_cost = null`/`unavailable`.
- `rate_limits` w zdarzeniu `token_count` — w spiku **nieobecne** (provider lokalny),
  więc nie można na nich opierać limitów. `unverified` przy providerach OpenAI.

## 10. Obserwacja modelu — kluczowe ograniczenie

- `turn_context.model` = **`auto_codex`**, czyli alias, nie realny model.
- Równoległe zapytanie do routera (`/v1/chat/completions`, `model: auto_codex`)
  zwróciło `"model": "qwen/Qwen3.8-Flash-Next"` — routing działa i **jest
  widoczny w polu `model` odpowiedzi chat/completions**.
- Codex używa `wire_api = "responses"`, a obecności pola `model` w odpowiedzi
  `/v1/responses` nie zweryfikowano → `model_observation: partial`.

Konsekwencja metodologiczna: przy routingu agenticznym AK-Bench **nie może**
ustalać zużycia modelu z danych agenta. Źródłem prawdy jest strona routera
(logi/metryki), a nie agent. Dotyczy to też eksperymentów „Auto Codex ON/OFF".

## 11. Izolacja plików i sieci

| Możliwość | Status | Uwagi |
|---|---|---|
| `read-only` / `workspace-write` / `danger-full-access` | verified | `-s`, wartość domyślna `read-only` |
| Sieć wyłączona domyślnie w `workspace-write` | verified (dokumentacja: `sandbox_workspace_write.network_access`, default `false`) | |
| `CODEX_SANDBOX_NETWORK_DISABLED=1` w środowisku procesu | verified (dokumentacja) | użyteczny sygnat weryfikacji |
| `sandbox_workspace_write.writable_roots` | verified (dokumentacja) | dodatkowe korzenie zapisu |
| `--dangerously-bypass-approvals-and-sandbox` | verified (istnieje) | testowane tylko w trybie zewnętrznego sandboxa |
| Docker jako warstwa AK-Bench | `unverified` w tej fazie | sandbox Codexa był wystarczający; Docker sprawdzony osobno (v29.2.1) |

## 12. Tabela capability dla `codex_cli` (propozycja do Agent Descriptor)

| Capability | Status | Uwaga |
|---|---|---|
| `workspace_binding` | verified | `-C` |
| `fresh_session` | verified | osobny proces + `CODEX_HOME` |
| `session_reset` | unsupported | tylko resume/fork |
| `task_submission` | verified | argument lub stdin |
| `completion_detection` | verified | `turn.completed` / `turn.failed` |
| `status_query` | partial | tylko strumień bieżącego procesu |
| `cancellation` | partial | sygnały procesowe, bez API |
| `token_usage` | verified | roll + strumień |
| `cost_usage` | unsupported | brak danych |
| `tool_trace` | verified | rollout + `item.completed` |
| `model_observation` | partial | alias `auto_codex`, realny model tylko po stronie routera |
| `streaming_output` | verified | `--json` |
| `filesystem_control` | verified | sandbox + `--add-dir` |
| `network_control` | verified | `sandbox_workspace_write.network_access` |
| `session_export` | verified | plik rollouta JSONL |
| `structured_output` | verified (dokumentacja) | `--output-schema` |

## 13. Ryzyka i niezgodności wykryte w spiku

1. **Zanieczyszczenie eksperymentów wiedzą.** Bieżąca sesja operatorska przechodzi
   przez ten sam router z włączonym `agentic_knowledge`, a blok `<agentic_knowledge>`
   był realnie wstrzykiwany w kontekst (widoczny w trakcie pracy nad tym repo).
   Warstwa wiedzy jest skopowana per repozytorium, więc runy benchmarku w tym
   samym repo mogą dziedziczyć wiedzę z sesji operatorskiej. Wymuszone:
   dedicated scope/KB dla benchmarku oraz weryfikacja stanu KB przed runem.
2. **Alias modelu zakrywa routing** (§10).
3. **Brak kosztu** (§9) — metryka kosztu musi pozostać `unavailable`, nie zero.
4. **Brak timeoutu i anulowania na poziomie agenta** (§7) — realne ograniczenie
   dla `retry_infrastructure_errors`.
5. **Rollout jako źródło trace'u jest ubocznym efektem zapisu sesji**; przy
   `--ephemeral` znika. Adapter musi to traktować jako zależność krytyczną.

## 14. Jak odtworzyć

```bash
# wymagane: LLM_ROUTER_API_KEY w środowisku
python3 spike/run_spike.py --dry-run          # tylko przygotowanie środowisk
python3 spike/run_spike.py --timeout 420      # pełny run E2E
```

Artefakty: `data/artifacts/spike/<run_id>/` — `manifest.json`,
`codex_stdout.jsonl`, `codex_stderr.log`, `agent_trace.jsonl`,
`tool_calls.jsonl`, `diff.patch`, `last_message.txt`, `evaluation.json`.
