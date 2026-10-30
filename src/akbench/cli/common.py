"""Shared CLI plumbing: context, console output, error handling."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from akbench.config.loader import LoadedConfig, load_settings
from akbench.core.errors import AKBenchmarkError
from akbench.core.logging_setup import configure_logging, get_logger

EXIT_OK = 0
EXIT_ERROR = 1

LOG = get_logger("cli")


@dataclass
class CliContext:
    """Lazily loaded configuration shared by all commands."""

    config_path: Path | None = None
    project_root: Path | None = None
    verbose: bool = False
    quiet: bool = False
    _loaded: LoadedConfig | None = field(default=None, repr=False)

    def loaded(self) -> LoadedConfig:
        if self._loaded is None:
            self._loaded = load_settings(
                self.config_path,
                project_root=self.project_root,
            )
        return self._loaded

    def apply_logging(self, *, min_level: str | None = None) -> None:
        """Configure logging. ``min_level`` raises the floor for machine output."""
        settings = self.loaded().settings
        level = settings.logging.level
        if self.verbose:
            level = "DEBUG"
        elif self.quiet:
            level = "ERROR"
        elif min_level is not None:
            ranking = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if ranking.index(min_level) > ranking.index(level):
                level = min_level
        log_file = None
        if settings.logging.to_file and settings.logging.file:
            from akbench.core.paths import resolve_path

            root = settings.project_root or Path.cwd()
            log_file = resolve_path(settings.logging.file, root)
        configure_logging(
            level,
            fmt=settings.logging.format,
            log_file=log_file,
            max_bytes=settings.logging.max_bytes,
            backup_count=settings.logging.backup_count,
        )


console = Console()
error_console = Console(stderr=True)


def show_json(data: Any) -> None:
    """Write JSON to stdout verbatim.

    Rich would wrap long values and inject newlines inside strings, which makes
    ``--json`` output unparseable when piped, so plain ``print`` is deliberate.
    Logs go to stderr, keeping stdout a clean JSON stream.
    """
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str), flush=True)


def emit(data: Any, *, as_json: bool, render: Callable[[], None]) -> None:
    """Print machine readable data, or fall back to the human renderer."""
    if as_json:
        show_json(data)
    else:
        render()


def fail(message: str, *, hint: str | None = None) -> typer.Exit:
    error_console.print(f"[red]error[/red] {message}")
    if hint:
        error_console.print(f"[dim]hint:[/dim] {hint}")
    return typer.Exit(EXIT_ERROR)


def handle_errors[P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Convert domain errors into exit code 1 instead of a traceback."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except AKBenchmarkError as exc:
            hint = getattr(exc, "hint", None)
            raise fail(str(exc), hint=hint) from exc
        except typer.Exit:
            raise
        except Exception as exc:  # unexpected: keep a trace for the log
            LOG.exception("unhandled error")
            raise fail(f"unexpected {type(exc).__name__}: {exc}") from exc

    return wrapper
