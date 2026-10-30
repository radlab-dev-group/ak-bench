# Faza 0 — integracyjny spike

Miniaturowy, samodzielny prototyp (wyłącznie biblioteka standardowa Pythona)
potwierdzający rzeczywiste możliwości integracji z agentem i routerem, zanim
powstanie właściwa platforma.

## Co robi

1. Tworzy izolowany workspace z fixture repo (`spike/repo`) i inicjuje repozytorium Git.
2. Tworzy izolowany `CODEX_HOME` z minimalnym `config.toml` (auth przez `env_key`,
   bez logowania) — dowód, że `fresh_agent_session` + `clean_agent_context` są wykonalne.
3. Uruchamia `codex exec --json` na zadaniu `spike/task.yaml` z timeoutem.
4. Parsuje strumień JSONL i rollout sesji: identyfikator sesji, tokeny,
   wywołania narzędzi, obserwowany model/sandbox.
5. Zapisuje `git diff` i ocenia wynik pytestem **poza** workspace agenta
   (wzorzec izolacji hidden tests).
6. Zapisuje Reproducibility Manifest z hashami artefaktów i rozdzieleniem
   `requested` / `effective` / `observed`.

## Uruchomienie

```bash
# wymagane: LLM_ROUTER_API_KEY w środowisku
python3 spike/run_spike.py --dry-run       # tylko przygotowanie środowisk
python3 spike/run_spike.py --timeout 420   # pełny run E2E
```

Artefakty trafiają do `data/artifacts/spike/<run_id>/` (katalog ignorowany przez Git).

## Wynik

Zweryfikowane fakty opisują: `docs/AGENT_INTEGRATION.md` oraz
`docs/ROUTER_INTEGRATION.md`. Dowód ostatniego udanego runu (manifest, diff,
ewaluacja, wywołania narzędzi) znajduje się w `spike/evidence/`.
