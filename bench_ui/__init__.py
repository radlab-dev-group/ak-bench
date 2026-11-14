"""AK-Bench UI package.

The re-exports below are lazy on purpose: ``import bench_ui`` must not build
the application. Building it reads the environment, opens the database and —
as any ASGI import string shows — an import that does work is an import that
fails in unrelated places (a user-add script does not want a dashboard).
"""

__all__ = ["app", "create_app"]


def __getattr__(name: str):
    if name in ("app", "create_app"):
        from bench_ui.app import app, create_app

        return {"app": app, "create_app": create_app}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
