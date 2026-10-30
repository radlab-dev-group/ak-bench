# AK-Bench

**Agentic Knowledge Benchmark** — rozszerzalna platforma do powtarzalnej oceny
agentów programistycznych, routerów LLM, modeli i pluginów rozszerzających ich
możliwości (bazy wiedzy, routing, optymalizacje).

Zasada nadrzędna: **testowany agent jest wymiennym komponentem**. AK-Bench nie
implementuje agenta, pamięci ani routingu — orkiestruje wykonanie zadań przez
wybranego agenta i niezależnie weryfikuje wynik.

## Status

| Faza | Zakres | Status |
|---|---|---|
| 0 | Integracyjny spike (Codex CLI + LLM Router) | ukończona |
| 1 | Szkielet: CLI, konfiguracja, logging, SQLite, migracje | ukończona |
| 2 | Deskryptory i registry | następna |

Pełny plan: `.plans/AK-Bench-implementation-plan.md`.

## Wymagania

- Python 3.12+ (najłatwiej przez [`uv`](https://docs.astral.sh/uv/))
- Git
- Docker — opcjonalnie, tylko do sandboxowania runów

## Szybki start

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"

akbench init          # katalogi + konfiguracja + baza (migracje do head)
akbench doctor        # gotowość środowiska
akbench config show   # efektywna konfiguracja i ścieżki
```

## Polecenia (Faza 1)

| Polecenie | Opis |
|---|---|
| `akbench version [--json]` | wersja AK-Bench i kluczowych zależności |
| `akbench init [--json] [--force-config] [--no-migrate]` | tworzy katalogi, konfigurację i schemat bazy |
| `akbench doctor [--json] [--strict]` | diagnostyka środowiska; exit 1 przy błędach |
| `akbench config show [--json] [--all]` | efektywna konfiguracja, ścieżki, URL bazy |
| `akbench config validate` | walidacja pliku konfiguracji bez zapisu |

Opcje globalne: `--config/-c`, `--project-root`, `--verbose/-v`, `--quiet/-q`, `--version`.

## Konfiguracja

Plik `configs/defaults.yaml`, nadpisywany zmiennymi środowiskowymi
`AKBENCH__SEKCJA__POLE`:

```bash
export AKBENCH__LOGGING__LEVEL=DEBUG
export AKBENCH__DATABASE__URL=sqlite:////tmp/akbench.sqlite
```

Wyszukiwanie konfiguracji: `--config` → `AKBENCH_CONFIG` →
`<korzeń projektu>/configs/defaults.yaml` → wartości wbudowane.
Korzeń projektu: `AKBENCH_HOME` → najbliższy przodek z `pyproject.toml` o nazwie
`ak-bench` → bieżący katalog.

Nieznane klucze są odrzucane — opcja milcząco zignorowana wyglądałaby na
skuteczną, a nie jest.

## Struktura

```text
src/akbench/
  cli/         # warstwa CLI (typer)
  config/      # modele Pydantic + ładowanie YAML/ENV
  core/        # błędy, ścieżki, czas, logowanie
  storage/     # SQLAlchemy, modele, migracje Alembic, runner migracji
  bootstrap.py # logika `akbench init`
  doctor.py    # diagnostyka środowiska
tests/
  unit/         # konfiguracja, ścieżki, storage, doctor
  integration/  # CLI
data/           # katalogi runów i baza (ignorowane przez git)
docs/           # dokumentacja integracji i rozwoju
spike/          # kod Fazy 0 (protokół przepływu)
```

## Dokumentacja

- `docs/AGENT_INTEGRATION.md` — zweryfikowane możliwości Codex CLI jako agenta
  (w tym to, czego API **nie** zapewnia: koszt, anulowanie, reset sesji)
- `docs/ROUTER_INTEGRATION.md` — LLM Router: healthcheck, modele, pluginy,
  metryki i ograniczenia weryfikacji
- `docs/DEVELOPMENT.md` — środowisko dev, testy, migracje

## Licencja

MIT — patrz `LICENSE`.
