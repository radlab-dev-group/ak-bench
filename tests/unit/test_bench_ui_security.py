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
    JUDGE,
    VIEWER,
    SecuritySettings,
    User,
    is_loopback,
    load_security_settings,
    parse_user,
    parse_users,
    require_valid_security,
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
            enabled=True, users=(User("ops", "long-enough-word"),), realm="AK-Bench"
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
