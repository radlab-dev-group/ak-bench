"""Entrypoint for running AK-Bench UI directly with `python -m bench_ui`."""

import sys

import uvicorn


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    reload = "--reload" in sys.argv or "-r" in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]

    print(f"Starting AK-Bench UI on http://{host}:{port}")
    uvicorn.run("bench_ui.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
