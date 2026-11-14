"""Tests for the dashboard's gate: who gets in, what they see, what they are told.

These cover the parts that exist because the dashboard is deployable outside a
laptop. The rest of the UI's tests declare a local instance and go about their
business; here the point is the boundary itself.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from bench_ui.app import create_app
from bench_ui.security import (
    ADMIN,
    JUDGE,
    VIEWER,
    Identity,
    SecuritySettings,
    User,
    is_loopback,
    issue_session,
    load_security_settings,
    parse_user,
    parse_users,
    require_valid_security,
    session_identity,
    session_key,
)
from bench_ui.service import _redact_task_yaml, scrub_ground_truth
from starlette.testclient import TestClient

from akbench.storage.migrator import upgrade

# ---------------------------------------------------------------- policy units


@pytest.fixture(autouse=True)
def _migrated_history(database_url: str) -> None:
    """The schema, so a page that reads history sees an empty one, not an error."""
    upgrade(database_url)


@pytest.mark.parametrize(
    "host, loopback",
    [
        ("127.0.0.1", True),
        ("127.9.9.9", True),  # all of 127/8 is loopback, not only .1
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),
        ("192.168.0.188", False),
        ("", False),  # unknown is not the same as private
        (None, False),
    ],
)
def test_only_a_loopback_address_reads_as_this_machine(
    host: str | None, loopback: bool
) -> None:
    assert is_loopback(host) is loopback


def test_a_secret_may_contain_a_colon() -> None:
    """Splitting on the first and last colon is what keeps a long secret whole."""
    user = parse_user("ops:a:b:c:judge")
    assert user.name == "ops"
    assert user.secret == "a:b:c"
    assert user.role == JUDGE


def test_an_entry_without_a_secret_is_refused() -> None:
    with pytest.raises(Exception, match="name:secret"):
        parse_user("ops")
    with pytest.raises(Exception, match="empty secret"):
        parse_user("ops:")


def test_the_same_name_twice_is_a_mistake() -> None:
    with pytest.raises(Exception, match="configured twice"):
        parse_users("ops:one123456789,ops:two123456789")


def test_auto_auth_off_on_loopback_and_on_otherwise(
    tmp_path: Path,
) -> None:
    local = load_security_settings({"AKBENCH_UI_BIND_HOST": "127.0.0.1"})
    assert local.enabled is False
    # An unauthenticated loopback instance is the single-user command line, and
    # that caller sees everything, answer key included.
    assert local.shows_ground_truth(None) is True

    away = load_security_settings(
        {"AKBENCH_UI_BIND_HOST": "0.0.0.0", "AKBENCH_UI_USERS": "ops:s3cret-s3cret"}
    )
    assert away.enabled is True
    assert away.shows_ground_truth(None) is False


def test_an_unknown_bind_address_is_treated_as_exposed() -> None:
    """Not knowing where the socket went is not evidence that it went nowhere."""
    settings = load_security_settings({})
    assert settings.enabled is True


def test_authentication_on_with_nobody_configured_refuses_to_serve() -> None:
    settings = load_security_settings({"AKBENCH_UI_BIND_HOST": "0.0.0.0"})
    assert settings.misconfiguration
    assert "AKBENCH_UI_USERS" in settings.misconfiguration
    with pytest.raises(Exception, match="nobody is configured"):
        require_valid_security(settings)


def test_a_viewer_and_a_judge_see_different_things() -> None:
    settings = SecuritySettings(enabled=True, users=(User("a", "s3cret-s3cret"),))
    assert settings.shows_ground_truth(_identity(VIEWER)) is False
    assert settings.shows_ground_truth(_identity(JUDGE)) is True
    assert settings.role_for("stranger") == VIEWER


def _identity(role: str):
    from bench_ui.security import Identity

    return Identity(name=f"someone-{role}", role=role)


# ------------------------------------------------------------ the served app


@pytest.fixture
def local_client(database_url: str) -> TestClient:
    """A dashboard on this machine: the gate is down, as it is for a laptop."""
    upgrade(database_url)
    app = create_app(database_url=database_url, security=SecuritySettings(enabled=False))
    return TestClient(app)


def test_a_loopback_dashboard_answers(local_client: TestClient) -> None:
    assert local_client.get("/").status_code == 200


def test_the_api_map_is_not_offered_to_whoever_asks(local_client: TestClient) -> None:
    """The interactive docs are a convenience turned reconnaissance when open."""
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert local_client.get(path).status_code == 404


def test_every_response_carries_the_security_headers(local_client: TestClient) -> None:
    response = local_client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    # Nothing is fetched from another origin, which is what kept the Chart.js
    # CDN from being a script-injection path.
    assert "default-src 'self'" in csp


def test_an_exposed_dashboard_demands_credentials(database_url: str) -> None:
    app = create_app(
        database_url=database_url,
        security=SecuritySettings(
            enabled=True,
            users=(User("ops", "long-enough-word"),),
            realm="AK-Bench",
            public_read=False,
        ),
    )
    client = TestClient(app)

    anonymous = client.get("/")
    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"].startswith("Basic realm=")
    # The refusal says nothing the status code did not already say: no path, no
    # echo of whatever was asked for.
    assert "/runs" not in anonymous.text

    wrong = client.get("/", headers=_basic("ops", "not-the-password"))
    assert wrong.status_code == 401
    unknown = client.get("/", headers=_basic("root", "long-enough-word"))
    assert unknown.status_code == 401

    admitted = client.get("/", headers=_basic("ops", "long-enough-word"))
    assert admitted.status_code == 200
    # A page behind credentials should not be left in a shared cache.
    assert admitted.headers["cache-control"] == "no-store"


def test_static_assets_are_served_before_anyone_signs_in(database_url: str) -> None:
    """CSS and JS carry no history, and a login page still needs its stylesheet."""
    app = create_app(
        database_url=database_url,
        security=SecuritySettings(enabled=True, users=(User("ops", "long-enough-word"),)),
    )
    client = TestClient(app)
    assert client.get("/static/js/app.js").status_code == 200


def test_a_gate_with_no_one_behind_it_serves_nothing(database_url: str) -> None:
    """Asked to authenticate, given nobody: 503 says so, an empty login box does not."""
    app = create_app(
        database_url=database_url, security=SecuritySettings(enabled=True)
    )
    client = TestClient(app)
    assert client.get("/").status_code == 503
    assert client.get("/api/runs").status_code == 503


def test_a_misconfigured_gate_is_reported_not_raised(database_url: str) -> None:
    """The module stays importable and the app constructible even so.

    uvicorn loads this app by import string, and a module that raises on import
    reports nothing at all; the refusal has to happen per request, loudly.
    """
    settings = load_security_settings(
        {"AKBENCH_UI_BIND_HOST": "0.0.0.0", "AKBENCH_UI_AUTH": "auto"}
    )
    app = create_app(database_url=database_url, security=settings)
    assert app.state.security.misconfiguration
    assert TestClient(app).get("/").status_code == 503


def _basic(name: str, secret: str) -> dict[str, str]:
    token = base64.b64encode(f"{name}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# ---------------------------------------------------- the answer key, scrubbed


def test_a_scrubbed_definition_keeps_the_task_and_loses_the_answers() -> None:
    definition = {
        "uid": "bookshop-stock-002@1.0.0",
        "title": "Release stock on cancel",
        "description": "Cancel must give the stock back.",
        "hidden_tests": "hidden_tests",
        "mutation": "--- a/orders.py\n-    return\n",
        "mutation_version": "1",
        "mutation_verification": "verified",
        "task_yaml": (
            "id: bookshop-stock-002\n"
            "version: 1.0.0\n"
            "title: Release stock on cancel\n"
            "task:\n"
            "  category: bug_fix\n"
            "  hidden_tests: hidden_tests\n"
            "  mutation:\n"
            "    patch: |\n"
            "      --- a/orders.py\n"
            "      -    return\n"
        ),
    }

    clean = scrub_ground_truth(definition)

    assert clean["title"] == "Release stock on cancel"
    assert clean["description"] == "Cancel must give the stock back."
    assert "hidden_tests" not in clean
    assert "mutation" not in clean
    assert "mutation_version" not in clean
    assert clean["ground_truth_withheld"] is True

    # The descriptor stays readable and stops being the answer.
    yaml_text = clean["task_yaml"]
    assert "bookshop-stock-002" in yaml_text
    assert "category: bug_fix" in yaml_text
    assert "hidden_tests" not in yaml_text
    assert "mutation" not in yaml_text


def test_a_descriptor_that_will_not_parse_is_dropped_not_shown() -> None:
    """An unreadable descriptor cannot be promised to be clean of them."""
    assert _redact_task_yaml("task: [unclosed") is None
    assert _redact_task_yaml(None) is None


def test_a_descriptor_without_answers_is_handed_through_unchanged() -> None:
    text = "id: wordcount-001\ntask:\n  category: bug_fix\n"
    assert _redact_task_yaml(text) == text


# ------------------------------------------------------------ login & sessions


def test_the_login_page_signs_a_caller_in(database_url: str) -> None:
    """The form answers the question the Basic box cannot explain.

    A browser is shown the login page rather than the credential box, a script
    keeps the 401 challenge it has always understood, and the cookie the form
    hands out opens the pages until it expires.
    """
    app = create_app(
        database_url=database_url,
        security=SecuritySettings(
            enabled=True,
            users=(
                User("ops", "long-enough-word", ADMIN),
                User("reader", "long-enough-word", VIEWER),
            ),
            public_read=False,
        ),
    )
    client = TestClient(app)

    page = client.get("/login")
    assert page.status_code == 200
    assert '<form method="post" action="/login"' in page.text

    browser = client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert browser.status_code == 303
    assert browser.headers["location"].startswith("/login?next=")

    assert client.get("/").status_code == 401

    wrong = client.post(
        "/login", data={"name": "ops", "password": "not-it", "next": "/runs"}
    )
    assert wrong.status_code == 200
    assert "Wrong name or password." in wrong.text

    signed_in = client.post(
        "/login",
        data={"name": "ops", "password": "long-enough-word", "next": "/runs"},
        follow_redirects=False,
    )
    assert signed_in.status_code == 303
    assert signed_in.headers["location"] == "/runs"
    assert "akbench_session=" in signed_in.headers["set-cookie"]

    home = client.get("/runs")
    assert home.status_code == 200
    assert "ops" in home.text  # the nav says who is signed in

    # an open redirect is not followed
    escape = client.post(
        "/login",
        data={"name": "ops", "password": "long-enough-word", "next": "//evil.example"},
        follow_redirects=False,
    )
    assert escape.headers["location"] == "/"

    out = client.get("/logout", follow_redirects=False)
    assert out.status_code == 303
    assert client.get("/api/runs").status_code == 401


def test_a_tampered_or_expired_session_cookie_proves_nothing() -> None:
    """What a cookie proves: a name, an expiry, and a signature over both."""
    import time

    settings = SecuritySettings(enabled=True, users=(User("ops", "long-enough-word", ADMIN),))
    key = session_key(settings)

    good = issue_session("ops", key)
    assert session_identity(f"akbench_session={good}", settings, key) == Identity(
        name="ops", role=ADMIN
    )
    # the role is read from the configuration, never from the cookie
    assert session_identity(f"akbench_session={good}", settings, key).is_admin

    tampered = good[:-6] + ("000000" if not good.endswith("000000") else "111111")
    assert session_identity(f"akbench_session={tampered}", settings, key) is None

    stale = issue_session("ops", key, now=time.time() - 400_000)
    assert session_identity(f"akbench_session={stale}", settings, key) is None

    gone = issue_session("ghost", key)
    assert session_identity(f"akbench_session={gone}", settings, key) is None

    assert session_identity("", settings, key) is None


def test_only_an_admin_deletes_and_only_with_the_header(database_url: str) -> None:
    """The admin gate is a role and a header: either one alone does not open it."""
    app = create_app(
        database_url=database_url,
        security=SecuritySettings(
            enabled=True,
            users=(
                User("root", "long-enough-word", ADMIN),
                User("reader", "long-enough-word", VIEWER),
            ),
        ),
    )
    client = TestClient(app)
    admin = _basic("root", "long-enough-word")
    reader = _basic("reader", "long-enough-word")

    assert client.get("/admin", headers=reader).status_code == 403
    assert client.get("/admin", headers=admin).status_code == 200

    # an admin without the confirmation header is still refused a delete
    assert (
        client.delete("/api/admin/runs/nope", headers=admin).status_code == 403
    )
    # a viewer with the header is still not an admin
    assert (
        client.delete(
            "/api/admin/runs/nope", headers={**reader, "X-Akbench-Admin": "1"}
        ).status_code
        == 403
    )
    # the two halves together reach the deletion, which then says 404 honestly
    assert (
        client.delete(
            "/api/admin/runs/nope", headers={**admin, "X-Akbench-Admin": "1"}
        ).status_code
        == 404
    )


def test_the_user_script_adds_a_hashed_user_to_the_database(tmp_path) -> None:
    """The script's words: one row, one hash, no secret left anywhere."""
    import os
    import subprocess

    from bench_ui import userstore

    db_url = f"sqlite:///{tmp_path}/ui-users.sqlite"
    upgrade(db_url)
    script = Path(__file__).resolve().parents[2] / "scripts" / "ui-user-add.sh"
    env = {**os.environ, "AKBENCH_UI_DATABASE_URL": db_url}

    added = subprocess.run(
        ["bash", str(script), "alice", "admin"],
        input="s3cret-s3cret\ns3cret-s3cret\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert added.returncode == 0, added.stderr
    assert "s3cret-s3cret" not in added.stdout  # never spoken back

    from akbench.storage.db import create_db_engine

    engine = create_db_engine(db_url)
    role, pw_hash = userstore.find_user(engine, "alice")
    assert role == "admin"
    assert "s3cret-s3cret" not in pw_hash  # the letters are gone
    assert pw_hash.startswith("pbkdf2_sha256$")  # the digest is what stayed
    assert userstore.verify_password("s3cret-s3cret", pw_hash)

    again = subprocess.run(
        ["bash", str(script), "alice"],
        input="x\nx\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert again.returncode != 0


def test_the_user_store_follows_the_env_file_to_the_database(tmp_path) -> None:
    """The .env speaks for the connection; silence means the SQLite file.

    The script must write its users where the app will read them — and the
    app reads its connection from the project's .env — so the two resolve the
    database with one walk, not two that could drift apart.
    """
    from bench_ui.userstore import database_url as resolve

    # nothing configured: the SQLite file a fresh checkout carries
    plain = resolve({}, project_root=tmp_path)
    assert plain.startswith("sqlite:///")
    assert plain.endswith("data/akbench.sqlite")

    # a .env as run-postgres.sh leaves it: the shared PostgreSQL database
    (tmp_path / ".env").write_text(
        "AKBENCH_DB_BACKEND=postgres\n"
        "AKBENCH_PG_HOST=db.example\n"
        "AKBENCH_PG_PORT=5432\n"
        "AKBENCH_PG_USER=akbench\n"
        "AKBENCH_PG_PASSWORD=hunter2\n"
        "AKBENCH_PG_DB=akbench\n",
        encoding="utf-8",
    )
    from_env = resolve({}, project_root=tmp_path)
    assert from_env.startswith("postgresql")
    assert "db.example" in from_env
    assert "akbench" in from_env

    # a real environment variable still wins over the file
    over = resolve(
        {"AKBENCH_UI_DATABASE_URL": "sqlite:////tmp/elsewhere.sqlite"},
        project_root=tmp_path,
    )
    assert over == "sqlite:////tmp/elsewhere.sqlite"


def test_a_database_user_signs_in_with_their_hash_and_signs_out(database_url: str) -> None:
    """The database answers for its people, and the cookie it grants signs out.

    What the row carries is a hash, what the login compares is the hash, and
    what the cookie carries is only the name. Signing out really signs out:
    the jar is told to forget the cookie and the door closes behind — even
    when a jar sends the value back wrapped in quotes, as some do.
    """
    import re as _re

    from bench_ui import userstore

    from akbench.storage.db import create_db_engine

    engine = create_db_engine(database_url)
    userstore.create_user(engine, "ada", "long-enough-word", "admin")
    userstore.create_user(engine, "bo", "long-enough-word", "viewer")

    app = create_app(
        database_url=database_url,
        security=SecuritySettings(enabled=True, users=(), public_read=False),
    )
    client = TestClient(app)

    wrong = client.post("/login", data={"name": "ada", "password": "not-it"})
    assert "Wrong name or password." in wrong.text

    signed_in = client.post(
        "/login",
        data={"name": "ada", "password": "long-enough-word", "next": "/admin"},
        follow_redirects=False,
    )
    assert signed_in.status_code == 303
    assert signed_in.headers["location"] == "/admin"

    admin_page = client.get("/admin")
    assert admin_page.status_code == 200
    assert "ada" in admin_page.text

    # a value sent back wrapped in quotes, as some cookie jars do, verifies
    value = _re.search(
        r"akbench_session=([^;]*)", signed_in.headers["set-cookie"]
    ).group(1)
    quoted = TestClient(app)
    home = quoted.get(
        "/",
        headers={"cookie": f'akbench_session="{value}"', "accept": "text/html"},
    )
    assert home.status_code == 200

    out = client.get("/logout", follow_redirects=False)
    assert out.status_code == 303
    assert out.headers["location"] == "/login?signed_out=1"
    assert "akbench_session=" in out.headers["set-cookie"]
    assert "Max-Age=0" in out.headers["set-cookie"]
    assert client.get("/api/runs").status_code == 401
    assert "Signed out." in client.get("/login?signed_out=1").text

    # a jar that kept the cookie anyway cannot spend it: the sign-out reached
    # the server, not only the browser
    replay = TestClient(app)
    stale = replay.get(
        "/",
        headers={"cookie": f'akbench_session="{value}"', "accept": "text/html"},
        follow_redirects=False,
    )
    assert stale.status_code == 303
    assert stale.headers["location"].startswith("/login")

    # the other database user keeps their own door and their own limits
    viewer = TestClient(app)
    viewer.post("/login", data={"name": "bo", "password": "long-enough-word"})
    assert viewer.get("/admin").status_code == 403


# ------------------------------------------- auto auth follows configured users
def test_auto_auth_turns_on_for_configured_users_even_on_loopback() -> None:
    """Loopback is also where a reverse proxy points; a user list is a request."""
    settings = load_security_settings(
        {"AKBENCH_UI_BIND_HOST": "127.0.0.1", "AKBENCH_UI_USERS": "ops:s3cret-s3cret"}
    )
    assert settings.enabled is True

    off = load_security_settings(
        {
            "AKBENCH_UI_BIND_HOST": "127.0.0.1",
            "AKBENCH_UI_USERS": "ops:s3cret-s3cret",
            "AKBENCH_UI_AUTH": "off",
        }
    )
    assert off.enabled is False


def test_a_database_user_makes_a_loopback_dashboard_ask_and_sign_out(
    database_url: str,
) -> None:
    """Sign-in and sign-out work on 127.0.0.1 once somebody has an account.

    Before, ``auto`` looked at the bind address only: the caller was the local
    admin on every request, ``/login`` bounced back to ``/`` and there was no
    way to be signed out.
    """
    from bench_ui import userstore

    from akbench.storage.db import create_db_engine

    userstore.create_user(
        create_db_engine(database_url), "ada", "long-enough-word", "admin"
    )
    settings = load_security_settings({"AKBENCH_UI_BIND_HOST": "127.0.0.1"})
    assert settings.enabled is False  # the environment alone says "local"
    app = create_app(database_url=database_url, security=settings)
    assert app.state.security.enabled is True
    client = TestClient(app, follow_redirects=False)
    html = {"Accept": "text/html"}

    refused = client.get("/admin", headers=html)
    assert refused.status_code == 303
    assert refused.headers["location"].startswith("/login")
    assert client.get("/login", headers=html).status_code == 200

    wrong = client.post("/login", content="name=ada&password=nope&next=/")
    assert "akbench_session" not in wrong.cookies
    signed_in = client.post(
        "/login", content="name=ada&password=long-enough-word&next=/admin"
    )
    assert signed_in.status_code == 303
    assert client.get("/admin", headers=html).status_code == 200

    out = client.get("/logout", headers=html)
    # Results are public by default, so signing out lands on them.
    assert out.headers["location"] == "/"
    assert client.get("/admin", headers=html).status_code == 303

    # An explicit "off" still means off, users or not.
    open_app = create_app(
        database_url=database_url,
        security=load_security_settings(
            {"AKBENCH_UI_BIND_HOST": "127.0.0.1", "AKBENCH_UI_AUTH": "off"}
        ),
    )
    assert TestClient(open_app).get("/admin", headers=html).status_code == 200


# ------------------------------------------------ public results, gated admin
def _public_app(database_url: str):
    return create_app(
        database_url=database_url,
        security=SecuritySettings(
            enabled=True,
            users=(
                User("ops", "long-enough-word", ADMIN),
                User("reader", "long-enough-word", VIEWER),
            ),
        ),
    )


def test_results_are_public_and_only_managing_them_needs_a_sign_in(
    database_url: str,
) -> None:
    """A reader sees the results; the Admin tab appears after signing in.

    Nothing asks an anonymous caller for a name: the pages and the read API
    answer, the navigation offers "Login", and only the Admin page and its
    deletes are closed.
    """
    client = TestClient(_public_app(database_url), follow_redirects=False)
    html = {"Accept": "text/html"}

    home = client.get("/", headers=html)
    assert home.status_code == 200
    assert 'href="/login?next=/"' in home.text
    assert 'href="/admin"' not in home.text
    assert 'href="/logout"' not in home.text
    assert client.get("/api/runs").status_code == 200
    assert client.get("/failures", headers=html).status_code == 200

    # Managing is closed: a browser is sent to sign in, a script gets the 401.
    page = client.get("/admin", headers=html)
    assert page.status_code == 303
    assert page.headers["location"] == "/login?next=%2Fadmin"
    refused = client.delete("/api/admin/runs/run-001", headers={"X-Akbench-Admin": "1"})
    assert refused.status_code == 401

    signed_in = client.post(
        "/login", content="name=ops&password=long-enough-word&next=/admin"
    )
    assert signed_in.headers["location"] == "/admin"
    home = client.get("/", headers=html)
    assert 'href="/admin"' in home.text
    assert 'href="/logout"' in home.text
    assert 'href="/login' not in home.text
    assert client.get("/admin", headers=html).status_code == 200

    out = client.get("/logout", headers=html)
    assert out.headers["location"] == "/"
    home = client.get("/", headers=html)
    assert home.status_code == 200
    assert 'href="/admin"' not in home.text
    assert client.get("/admin", headers=html).status_code == 303


def test_a_public_reader_is_not_an_admin_a_judge_or_a_failed_login(
    database_url: str,
) -> None:
    app = _public_app(database_url)
    client = TestClient(app, follow_redirects=False)

    # The answer key stays with judges and admins.
    assert app.state.security.shows_ground_truth(None) is False
    # Credentials that were offered and are wrong are refused, not ignored.
    wrong = client.get("/", headers=_basic("ops", "not-the-password"))
    assert wrong.status_code == 401
    # A signed-in viewer still cannot manage.
    as_reader = client.get("/admin", headers=_basic("reader", "long-enough-word"))
    assert as_reader.status_code == 403
    as_admin = client.get("/admin", headers=_basic("ops", "long-enough-word"))
    assert as_admin.status_code == 200


def test_public_read_can_be_switched_off() -> None:
    assert load_security_settings({}).public_read is True
    closed = load_security_settings({"AKBENCH_UI_PUBLIC_READ": "off"})
    assert closed.public_read is False
    assert closed.requires_sign_in("/") is True
    opened = load_security_settings({"AKBENCH_UI_PUBLIC_READ": "on"})
    assert opened.requires_sign_in("/runs") is False
    assert opened.requires_sign_in("/admin") is True
    assert opened.requires_sign_in("/api/admin/runs/x") is True
    assert opened.requires_sign_in("/administrator") is False
    assert load_security_settings({"AKBENCH_UI_PUBLIC_READ": "maybe"}).misconfiguration
