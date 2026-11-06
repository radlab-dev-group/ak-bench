#!/usr/bin/env python3
"""Fill in what the recorded tasks ask for, from the dataset on disk.

History used to store a task's identity without its prose: the title, the
description, the descriptor itself and ``description.md`` stayed in the dataset
directory, so a task page could only name a task, not describe it. The columns
exist from migration ``0008``; this script fills them for the rows that
predate it, and refreshes them when a descriptor has been edited since the last
run.

The connection comes from the project configuration (``.env``), so the script
targets the same PostgreSQL the CLI and the UI use.

    scripts/update_task_info.py                  # backfill the configured database
    scripts/update_task_info.py --dry-run        # report, change nothing
    scripts/update_task_info.py --datasets ../ak-bench-data/datasets
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

import yaml  # noqa: E402
from sqlalchemy import Engine, make_url, select  # noqa: E402

from akbench.config.loader import load_settings, resolve_database_url  # noqa: E402
from akbench.core.errors import AKBenchmarkError  # noqa: E402
from akbench.core.time import utc_now  # noqa: E402
from akbench.datasets.dataset import DESCRIPTION_FILE, TASK_FILE, Dataset  # noqa: E402
from akbench.descriptors import DescriptorKind, load_registry  # noqa: E402
from akbench.storage.db import create_db_engine, session_scope  # noqa: E402
from akbench.storage.history import HistoryStore  # noqa: E402
from akbench.storage.migrator import head_revision, schema_status, upgrade  # noqa: E402
from akbench.storage.models import Agent, Experiment, Runtime, Task, TaskRun  # noqa: E402


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _authors_json(task: Any) -> str | None:
    authors = list(getattr(task, "authors", None) or [])
    if not authors:
        return None
    return json.dumps(authors, ensure_ascii=False, default=str, sort_keys=True)


def _content(loaded: Any) -> dict[str, Any]:
    """The content columns for one task found on disk."""
    descriptor = loaded.task
    body = descriptor.task
    return {
        "title": descriptor.title,
        "description": descriptor.description,
        "authors_json": _authors_json(descriptor),
        "task_created_at": getattr(descriptor, "created_at", None),
        "task_yaml": _read_text(Path(loaded.path) / TASK_FILE),
        "description_md": _read_text(Path(loaded.path) / DESCRIPTION_FILE),
        "category": body.category,
        "difficulty": body.difficulty,
        "evaluator": body.evaluator,
    }


def _changes(row: Task, content: dict[str, Any]) -> dict[str, Any]:
    """The columns whose recorded value differs from the descriptor."""
    wanted = {key: value for key, value in content.items() if value is not None}
    current = {key: getattr(row, key) for key in wanted}
    changed = {
        key: value
        for key, value in wanted.items()
        if current.get(key) != value
    }
    return changed


def _index(dataset: Dataset) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    by_uid = {loaded.uid: loaded for loaded in dataset.tasks}
    by_id: dict[str, list[Any]] = {}
    for loaded in dataset.tasks:
        by_id.setdefault(str(loaded.task.id), []).append(loaded)
    return by_uid, by_id


def backfill(
    engine: Engine, dataset: Dataset, *, dry_run: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    """Write the task content into every recorded row this dataset can name."""
    by_uid, by_id = _index(dataset)
    updated: list[dict[str, Any]] = []
    unresolved: list[str] = []

    with session_scope(engine) as session:
        rows = session.scalars(select(Task).order_by(Task.uid)).all()
        for row in rows:
            loaded = by_uid.get(row.uid)
            if loaded is None:
                candidates = by_id.get(row.task_id, [])
                loaded = candidates[0] if len(candidates) == 1 else None
            if loaded is None:
                unresolved.append(row.uid)
                continue

            content = _content(loaded)
            changed = _changes(row, content)
            if not changed:
                continue
            if not dry_run:
                for key, value in changed.items():
                    setattr(row, key, value)
            updated.append({"uid": row.uid, "fields": sorted(changed)})

    return updated, unresolved


def _backfill_task_files(
    store: HistoryStore, dataset: Dataset, *, dry_run: bool = False
) -> tuple[int, int, list[str]]:
    """Record each task's code from the dataset, reporting how much changed.

    Returns ``(tasks_with_code, files_changed, unresolved)``. A task whose
    repository source is a remote URL has no local files to read and is left
    as recorded, not reported as broken.
    """
    by_uid = {loaded.uid: loaded for loaded in dataset.tasks}
    by_id: dict[str, list[Any]] = {}
    for loaded in dataset.tasks:
        by_id.setdefault(str(loaded.task.id), []).append(loaded)

    with session_scope(store.engine) as session:
        targets = [
            (row.uid, row.task_id)
            for row in session.scalars(select(Task).order_by(Task.uid)).all()
        ]

    with_code = 0
    changed = 0
    unresolved: list[str] = []
    for uid, task_id in targets:
        loaded = by_uid.get(uid)
        if loaded is None:
            candidates = by_id.get(task_id, [])
            loaded = candidates[0] if len(candidates) == 1 else None
        if loaded is None:
            unresolved.append(uid)
            continue
        if not dry_run:
            delta = store.record_task_files(loaded)
            if delta:
                changed += delta
        if _has_code(loaded):
            with_code += 1
    return with_code, changed, unresolved


def _has_code(loaded: Any) -> bool:
    """Whether a task on disk names local files worth recording."""
    from akbench.storage.history import collect_task_files

    return bool(collect_task_files(loaded))


def _descriptor_text(entry: Any) -> str | None:
    """The file a descriptor was read from, when it still exists."""
    source = getattr(entry, "source", None)
    if source is None:
        return None
    with contextlib.suppress(OSError):
        return Path(source).read_text(encoding="utf-8")
    return None


def _backfill_components(engine: Engine) -> int:
    """The agents and runtimes the history names, from the descriptor tree.

    A run that names an agent or runtime names a row; this fills those rows
    from ``descriptors/`` so a stored run can be read next to the instrument
    that produced it. A component the registry does not carry is left as is:
    an unknown row is a fact the script cannot invent.
    """
    with session_scope(engine) as session:
        agent_ids = {
            row[0] for row in session.execute(select(TaskRun.agent_id)).all() if row[0]
        }
        runtime_ids = {
            row[0] for row in session.execute(select(TaskRun.runtime_id)).all() if row[0]
        }
    try:
        registry = load_registry(PROJECT_ROOT / "descriptors")
    except Exception:
        return 0

    filled = 0
    for kind, model, body_name, ids in (
        (DescriptorKind.AGENT, Agent, "agent", agent_ids),
        (DescriptorKind.RUNTIME, Runtime, "runtime", runtime_ids),
    ):
        for identifier in sorted(ids):
            entry = registry.get(kind, identifier)
            if entry is None:
                print(f"  ! {body_name} {identifier!r}: not in descriptors/, left as recorded")
                continue
            document = _descriptor_text(entry)
            payload = entry.snapshot.payload
            version = str(entry.snapshot.version)
            column = f"{body_name}_yaml"
            with session_scope(engine) as session:
                row = session.scalar(
                    select(model).where(
                        getattr(model, f"{body_name}_id") == identifier,
                        model.version == version,
                    )
                )
                if row is None:
                    session.add(
                        model(
                            **{
                                f"{body_name}_id": identifier,
                                "version": version,
                                "title": payload.get("title"),
                                "description": payload.get("description"),
                                column: document,
                                "created_at": utc_now(),
                                "updated_at": utc_now(),
                            }
                        )
                    )
                    filled += 1
                elif document and not getattr(row, column):
                    setattr(row, column, document)
                    row.updated_at = utc_now()
                    filled += 1
    return filled


def _backfill_experiments(engine: Engine) -> int:
    """The experiment rows that can be matched to a configuration file.

    The file under ``configs/experiments/`` is matched by the descriptor id
    the experiment row carries; its text is what the page quotes. Rows whose
    configuration no longer exists are left as recorded and named.
    """
    config_dir = PROJECT_ROOT / "configs" / "experiments"
    if not config_dir.is_dir():
        return 0
    by_id: dict[str, str] = {}
    for path in sorted(config_dir.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(document, dict) and document.get("id"):
            by_id[str(document["id"])] = path.read_text(encoding="utf-8")
    if not by_id:
        return 0
    filled = 0
    with session_scope(engine) as session:
        rows = session.scalars(select(Experiment)).all()
        for row in rows:
            document = by_id.get(str(row.descriptor_id or ""))
            if document and not row.experiment_yaml:
                row.experiment_yaml = document
                row.updated_at = utc_now()
                filled += 1
    return filled


def _report(updated: list[dict[str, Any]], unresolved: list[str], total: int) -> None:
    if updated:
        print(f"{'TASK UID':<40} FIELDS")
        for entry in updated:
            print(f"{entry['uid']:<40} {', '.join(entry['fields'])}")
    else:
        print("no recorded task needed a change")
    for uid in unresolved:
        print(f"  ! {uid}: not in the dataset, left as recorded")
    print(
        f"\n{total} task rows: {len(updated)} with content "
        f"({'to update' if unresolved or updated else 'checked'}, "
        f"{len(unresolved)} unresolved)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="update_task_info.py",
        description="Backfill task titles, descriptions, descriptors and authors.",
    )
    parser.add_argument(
        "--datasets",
        type=Path,
        default=None,
        help="dataset directory to read (default: <project>/datasets)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="database to update (default: the one in .env / configs/defaults.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    parser.add_argument(
        "--tasks-only",
        action="store_true",
        help="backfill task content only (skip experiments, agents and runtimes)",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="do not bring the schema to head first (it must already be there)",
    )
    args = parser.parse_args(argv)

    try:
        loaded_config = load_settings(None, project_root=PROJECT_ROOT)
        database_url = args.database_url or resolve_database_url(loaded_config.settings)
    except AKBenchmarkError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    datasets_dir = args.datasets or PROJECT_ROOT / "datasets"
    if not datasets_dir.is_dir():
        print(f"dataset directory not found: {datasets_dir}", file=sys.stderr)
        return 2

    try:
        dataset = Dataset.load(datasets_dir, base_dir=PROJECT_ROOT)
    except Exception as exc:
        print(f"cannot read dataset {datasets_dir}: {exc}", file=sys.stderr)
        return 2

    print(f"database: {_target(database_url)}")
    print(f"datasets: {datasets_dir} ({len(dataset)} tasks)")

    if not args.skip_migrations:
        before, after = upgrade(database_url)
        status = schema_status(database_url)
        print(f"schema: {before or 'unversioned'} -> {status.current} (head {head_revision()})")
        if after != head_revision():  # pragma: no cover - upgrade went to head
            print(
                "database is not at the head revision; run `akbench migrate upgrade`",
                file=sys.stderr,
            )
            return 2

    engine = create_db_engine(database_url)
    try:
        try:
            updated, unresolved = backfill(engine, dataset, dry_run=args.dry_run)
            with session_scope(engine) as session:
                total = len(session.scalars(select(Task.uid)).all())
        except Exception as exc:
            print(f"cannot update tasks: {exc}", file=sys.stderr)
            return 1

        _report(updated, unresolved, total)

        store = HistoryStore(engine)
        with_code, files_changed, file_unresolved = _backfill_task_files(
            store, dataset, dry_run=args.dry_run
        )
        if file_unresolved:
            print(f"  ! {len(file_unresolved)} recorded task(s) had no files to backfill")
        if args.dry_run:
            print(f"\ntask files: {with_code} task(s) with local code to record")
        else:
            print(f"\ntask files: {files_changed} file(s) recorded for {with_code} task(s)")

        if args.tasks_only:
            return 0
        if args.dry_run:
            print(
                "\nexperiments, agents and runtimes: "
                "would be refreshed from configs/ and descriptors/"
            )
        else:
            experiments_filled = _backfill_experiments(engine)
            components_filled = _backfill_components(engine)
            print(f"\nexperiments: {experiments_filled} with their configuration file")
            print(f"components: {components_filled} agent/runtime rows filled")
        return 0
    finally:
        engine.dispose()


def _target(database_url: str) -> str:
    """Which database is being written, without its address or credentials."""
    url = make_url(database_url)
    if url.drivername.startswith("sqlite"):
        return f"sqlite {url.database}"
    return f"{url.drivername.split('+')[0]} database {url.database}"


if __name__ == "__main__":
    raise SystemExit(main())
