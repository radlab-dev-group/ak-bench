"""Entrypoint for running AK-Bench UI directly with `python -m bench_ui`."""

import os
import sys

import uvicorn


def _read_option(argv: list[str], name: str, default: str) -> str:
    """``--name value`` and ``--name=value``, both, because ``run-ui.sh`` and a
    person typing by hand do not agree on which one they will use.

    Accepting only one form was a quiet hazard rather than a small annoyance:
    the script passes ``--host 0.0.0.0`` spaced, this parser looked for
    ``--host=``, found neither, and started the dashboard somewhere else than
    the operator had asked for.
    """
    for index, arg in enumerate(argv):
        if arg == f"--{name}" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(f"--{name}="):
            return arg.split("=", 1)[1]
    return default


def main() -> None:
    argv = sys.argv[1:]
    host = _read_option(argv, "host", "127.0.0.1")
    port = int(_read_option(argv, "port", "8000"))
    reload = "--reload" in argv or "-r" in argv

    # The app is imported by uvicorn in a process of its own, so the address it
    # was asked for travels the only way that reaches it: the environment.
    os.environ["AKBENCH_UI_BIND_HOST"] = host

    from bench_ui.security import is_loopback, load_security_settings

    security = load_security_settings()
    print(f"Starting AK-Bench UI on http://{host}:{port}")
    print(f"  auth: {security.describe()}")
    if security.misconfiguration:
        print(
            "  the dashboard will refuse every request until this is fixed",
            file=sys.stderr,
        )
    elif not is_loopback(host):
        print(
            "  warning: reachable from outside this machine; put TLS in front "
            "of it, or the password crosses the network in the clear",
            file=sys.stderr,
        )

    uvicorn.run("bench_ui.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
