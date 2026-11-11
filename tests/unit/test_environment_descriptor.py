"""The environment descriptor: where a run says it executed.

An experiment may name its environment the way it names its agent; the
descriptor is what makes that reference checkable. These tests pin the
validation rules — a docker sandbox needs an image, a host one must not have
one — and the round trip through the registry, which is what a plan's
snapshot relies on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from akbench.descriptors import DescriptorKind, load_registry
from akbench.descriptors.environment import EnvironmentDescriptor, SandboxKind

REPO_ROOT = Path(__file__).resolve().parents[2]


def payload(**environment: object) -> dict:
    body = {
        "os": "linux",
        "python": "3.12",
        "tools": ["git"],
        "network": True,
        "filesystem": "workspace",
        "sandbox": "host",
    }
    body.update(environment)
    return {
        "schema_version": "1.0",
        "id": "test-env",
        "version": "1.0.0",
        "environment": body,
    }


def test_a_host_environment_validates() -> None:
    descriptor = EnvironmentDescriptor.model_validate(payload())
    assert descriptor.environment.sandbox is SandboxKind.HOST
    assert descriptor.environment.image is None


def test_a_docker_environment_needs_an_image() -> None:
    descriptor = EnvironmentDescriptor.model_validate(
        payload(sandbox="docker", image="python:3.12-slim")
    )
    assert descriptor.environment.sandbox is SandboxKind.DOCKER
    assert descriptor.supports_sandbox("docker")
    assert descriptor.supports_sandbox(SandboxKind.DOCKER) is True
    assert descriptor.supports_sandbox("host") is False

    with pytest.raises(ValidationError, match="image"):
        EnvironmentDescriptor.model_validate(payload(sandbox="docker"))


def test_a_host_environment_rejects_an_image() -> None:
    with pytest.raises(ValidationError, match="image"):
        EnvironmentDescriptor.model_validate(payload(image="python:3.12-slim"))


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        EnvironmentDescriptor.model_validate(payload(**{"container": "no"}))


def test_the_shipped_environments_round_trip_through_the_registry() -> None:
    registry = load_registry(REPO_ROOT / "descriptors")
    entries = {entry.snapshot.id: entry for entry in registry.entries(DescriptorKind.ENVIRONMENT)}

    assert set(entries) == {"local-host", "docker-python312"}
    local = entries["local-host"].descriptor
    assert isinstance(local, EnvironmentDescriptor)
    assert local.environment.sandbox is SandboxKind.HOST
    # A snapshot digest is what a plan pins; the shipped file must carry one.
    assert entries["local-host"].snapshot.digest.startswith("sha256:")
    assert entries["docker-python312"].snapshot.digest.startswith("sha256:")
