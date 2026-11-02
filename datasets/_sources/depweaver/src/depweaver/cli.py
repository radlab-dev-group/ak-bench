"""Offline project, repository and lockfile command line interface."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import codec
from .audit import Database, audit, summarize
from .catalog import inspect
from .errors import SearchLimit, Unsatisfiable
from .explain import Explanation, render_conflict
from .graph import Graph
from .inventory import Inventory
from .lockfile import Lockfile, diff
from .manifest import Manifest
from .matrix import profiles
from .model import canonical
from .planner import Installed, Plan, plan
from .repository import Repository
from .resolver import Resolver
from .validation import require_valid


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="depweaver", description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    solve = commands.add_parser("solve", help="resolve a JSON request or TOML manifest")
    solve.add_argument("repository", type=Path)
    source = solve.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", type=Path)
    source.add_argument("--manifest", type=Path)
    solve.add_argument("--profile")
    solve.add_argument("--group", action="append", default=[])
    solve.add_argument("--lock", type=Path)
    solve.add_argument("--update", action="append", default=[])
    solve.add_argument("--output", type=Path)
    matrix = commands.add_parser("matrix", help="resolve all manifest profiles")
    matrix.add_argument("repository", type=Path)
    matrix.add_argument("manifest", type=Path)
    matrix.add_argument("--profile", action="append", default=[])
    matrix.add_argument("--output", type=Path)
    check = commands.add_parser("verify", help="validate lock against metadata and request")
    check.add_argument("repository", type=Path)
    check.add_argument("request", type=Path)
    check.add_argument("lock", type=Path)
    graph = commands.add_parser("graph", help="display lock dependency graph")
    graph.add_argument("lock", type=Path)
    graph.add_argument("--dot", action="store_true")
    explain = commands.add_parser("explain", help="explain why a package is selected")
    explain.add_argument("repository", type=Path)
    explain.add_argument("request", type=Path)
    explain.add_argument("lock", type=Path)
    explain.add_argument("package", nargs="?")
    difference = commands.add_parser("diff", help="compare two lockfiles")
    difference.add_argument("before", type=Path)
    difference.add_argument("after", type=Path)
    inspect_parser = commands.add_parser("inspect", help="inspect repository metadata")
    inspect_parser.add_argument("repository", type=Path)
    audit_parser = commands.add_parser("audit", help="match offline advisories")
    audit_parser.add_argument("repository", type=Path)
    audit_parser.add_argument("lock", type=Path)
    audit_parser.add_argument("database", type=Path)
    audit_parser.add_argument(
        "--minimum", choices=("low", "moderate", "high", "critical"), default="low"
    )
    audit_parser.add_argument("--ignore", action="append", default=[])
    inventory = commands.add_parser("inventory", help="export reproducible software inventory")
    inventory.add_argument("lock", type=Path)
    inventory.add_argument("--output", type=Path)
    planning = commands.add_parser("plan", help="plan an installed environment transition")
    planning.add_argument("installed", type=Path)
    planning.add_argument("lock", type=Path)
    planning.add_argument("--output", type=Path)
    application = commands.add_parser(
        "apply-plan", help="apply a plan to an offline environment document"
    )
    application.add_argument("installed", type=Path)
    application.add_argument("plan", type=Path)
    application.add_argument("--output", type=Path)
    return result


def emit(document: object, output: Path | None = None) -> None:
    if output is not None:
        codec.write(output, document)
    else:
        print(canonical(document))


def dispatch(arguments: argparse.Namespace) -> int:
    command = arguments.command
    if command == "solve":
        repository = Repository.read(arguments.repository)
        if arguments.request:
            if arguments.profile or arguments.group:
                raise ValueError("profiles/groups require a manifest")
            request = codec.request(codec.read(arguments.request))
        else:
            request = Manifest.read(arguments.manifest).request(
                arguments.profile, groups=tuple(arguments.group)
            )
        if arguments.lock:
            request = Lockfile.read(arguments.lock).request(
                request.roots,
                update=frozenset(arguments.update),
                target=request.target,
                policy=request.policy,
            )
        elif arguments.update:
            raise ValueError("--update requires --lock")
        resolution = Resolver(repository).solve(request)
        require_valid(repository, request, resolution)
        emit(Lockfile(resolution).document(), arguments.output)
    elif command == "matrix":
        result = profiles(
            Repository.read(arguments.repository),
            Manifest.read(arguments.manifest),
            names=tuple(arguments.profile),
        )
        emit(
            {
                "bundle": result.bundle.document(),
                "failures": [asdict(failure) for failure in result.failures],
            },
            arguments.output,
        )
        return 0 if result.ok else 1
    elif command == "verify":
        repository = Repository.read(arguments.repository)
        lock = Lockfile.read(arguments.lock)
        request = codec.request(codec.read(arguments.request))
        lock.verify_repository(repository)
        require_valid(repository, request, lock.resolution)
        emit({"ok": True})
    elif command == "graph":
        graph = Graph.from_resolution(Lockfile.read(arguments.lock).resolution)
        if arguments.dot:
            print(graph.dot(), end="")
        else:
            emit(graph.document())
    elif command == "explain":
        explanation = Explanation(
            Repository.read(arguments.repository),
            codec.request(codec.read(arguments.request)),
            Lockfile.read(arguments.lock).resolution,
        )
        emit(
            explanation.package(arguments.package) if arguments.package else explanation.document()
        )
    elif command == "diff":
        emit(asdict(diff(Lockfile.read(arguments.before), Lockfile.read(arguments.after))))
    elif command == "inspect":
        repository = Repository.read(arguments.repository)
        issues = inspect(repository)
        emit(
            {
                "repository": repository.fingerprint,
                "packages": len(repository.names()),
                "releases": len(repository.all()),
                "issues": [issue.document() for issue in issues],
            }
        )
        return 1 if issues else 0
    elif command == "audit":
        findings = audit(
            Repository.read(arguments.repository),
            Lockfile.read(arguments.lock).resolution,
            Database.load(codec.read(arguments.database)),
            minimum=arguments.minimum,
            ignored=frozenset(arguments.ignore),
        )
        emit(
            {
                "summary": summarize(findings),
                "findings": [finding.document() for finding in findings],
            }
        )
        return 1 if findings else 0
    elif command == "inventory":
        emit(
            Inventory.from_resolution(Lockfile.read(arguments.lock).resolution).document(),
            arguments.output,
        )
    elif command == "plan":
        emit(
            plan(
                Installed.load(codec.read(arguments.installed)),
                Lockfile.read(arguments.lock).resolution,
            ).document(),
            arguments.output,
        )
    elif command == "apply-plan":
        emit(
            Plan.load(codec.read(arguments.plan))
            .apply(Installed.load(codec.read(arguments.installed)))
            .document(),
            arguments.output,
        )
    else:
        raise ValueError("unknown command")
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        return dispatch(arguments)
    except Unsatisfiable as error:
        print(render_conflict(error.conflict), file=sys.stderr)
        return 1
    except SearchLimit as error:
        print("Search limit: " + str(error), file=sys.stderr)
        return 3
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print("Invalid input: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
