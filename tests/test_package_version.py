"""The package reports the version its pyproject declares."""

import tomllib
from pathlib import Path

import downlink


def test_the_package_reports_the_version_its_pyproject_declares():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert downlink.__version__ == declared
