# Środowisko developerskie

## 1. Setup

```bash
uv venv --python 3.12 .venv          # systemowy python to 3.10 — nie wystarczy
uv pip install -e ".[dev]"
akbench init
akbench doctor
```

`uv` nie jest wymagany przez pakiet, ale system nie ma Pythona 3.12, a
`requires-python` to `>=3.12`. Alternatywa: dowolne `venv` na Pythonie 3.12.

## 2. Testy i lintowanie

```bash
.venv/bin/python -m pytest -q          # całość
.venv/bin/python -m pytest tests/unit -q
.venv/bin/ruff check src tests
.venv/bin/ruff check src tests --fix
```

Testy nie wymagają sieci ani agenta: działają na tymczasowych katalogach i
bazach SQLite. Testy integracyjne (CLI) używają `typer.testing.CliRunner`.

Kontrakty warte uwagi:

- `tests/unit/test_migrations_match_models.py` — porównuje schemat po migracji
  z `Base.metadata` przez `alembic.autogenerate.compare_metadata`. Migracja,
  która rozjedzie się z modelami, psuje ten test.
- `tests/integration/test_cli.py` — kody wyjścia i kształt wyjścia `--json`.

## 3. Migracje

Skrypty Alembic mieszkają **wewnątrz pakietu**
(`src/akbench/storage/migrations/`), więc działają po `pip install` bez
`alembic.ini`. Wywołanie programowe: `akbench.storage.migrator`.

Nowa migracja:

```bash
AKBENCH_MIGRATION_DATABASE_URL="sqlite:///$PWD/data/akbench.sqlite" \
  .venv/bin/alembic -c /dev/stdin revision --autogenerate --name "coś"
```


Ponieważ `script_location` wskazuje na pakiet, najczęściej wystarczy jednak
ręcznie dodać plik w `versions/` na wzorzec `0001_core_tables.py`, a potem
uruchomić `akbench init` (stosuje migracje) i test kontraktowy powyżej.

Zasady:
- SQLite + `render_as_batch=True` (limit ALTER TABLE),
- `task_uid` w `task_runs` to na razie plain string — właściwy FK do `tasks`
  pojawi się w Fazie 3,
- pełny model danych (metryki, obserwacje, snapshoty deskryptorów, zdarzenia)
  w Faza 11.

## 4. Konwencje kodu

- Python 3.12 (PEP 695 w generykach), `from __future__ import annotations`,
  typowane wszystkie sygnatury.
- Wyjątki z `akbench.core.errors` niosą `failure_class` — błąd infrastruktury
  nie może wyglądać jak błąd agenta (plan, zasada 11).
- Nazwy agentów (np. `codex`) nie pojawiają się w ogólnym runnerze, schedulerze
  ani evaluatorze; narzędzia zewnętrzne konfiguruje `doctor.required_tools`.
- Wyjście `--json` pisze czysty JSON na stdout (bez rich — rich łamie linie),
  logi idą na stderr. Dzięki temu `akbench doctor --json | jq` działa, także z
  `2>&1`.
- Linie do 100 znaków (`ruff`, `E501`).

## 5. Co jest celowo niedokończone

- Komendy `agent`, `dataset`, `experiment`, `report`, `export` — Fazy 2+.
- Tabela `tasks` i relacje — Faza 3.
- Warstwa obserwabilności i metryk — Fazy 9 i 11.
- Sandbox Docker — Faza 3/7 (sprawdzona dostępność Dockera, brak implementacji).
