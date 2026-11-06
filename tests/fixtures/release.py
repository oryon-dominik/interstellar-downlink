"""The release numberer, for its contract test."""

import importlib.util
import sys
from pathlib import Path

import pytest


def repository() -> Path:
    """The repository root: two levels above this fixtures module."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def version_script():
    """The release numberer, imported by path — `scripts` is no package."""
    spec = importlib.util.spec_from_file_location("release_version", repository() / "scripts" / "version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("release_version", None)


@pytest.fixture
def project_pyproject() -> Path:
    """The pyproject that declares the release-tag shape."""
    return repository() / "pyproject.toml"
