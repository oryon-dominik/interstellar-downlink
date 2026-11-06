"""One log format for every process: shared rotating files, crash capture, a live console switch, a reader.

Import the package and call through it: ``downlink.configure(...)``, ``downlink.record_crashes(logger)``,
``"()": "downlink.DeckLevelFilter"`` in a logging configuration. Setting the deck level stays qualified
under ``downlink.decklevel``: only whoever owns the switch needs it.
"""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from downlink.console import ConsoleHandler
from downlink.crashlog import record_crashes
from downlink.decklevel import NOTICE, DeckLevelFilter, allowed
from downlink.files import configure
from downlink.logformat import (
    DATE_FORMAT,
    DJANGO_VERBOSE,
    ERROR_LEVELS,
    LINE_FORMAT,
    ReadRecord,
    is_trouble,
    newest_first,
    records_since,
)
from downlink.stamps import StampFormatter, clock, stamp

__all__ = [
    "DATE_FORMAT",
    "DJANGO_VERBOSE",
    "ERROR_LEVELS",
    "LINE_FORMAT",
    "NOTICE",
    "ConsoleHandler",
    "DeckLevelFilter",
    "ReadRecord",
    "StampFormatter",
    "allowed",
    "clock",
    "configure",
    "is_trouble",
    "newest_first",
    "record_crashes",
    "records_since",
    "stamp",
]


def _resolve_version() -> str:
    """Return the version pyproject.toml declares, wherever it is reachable.

    An installed package answers from its metadata — the wheel ships METADATA, never
    pyproject.toml. Only a source tree that was never installed reads the file itself.
    """
    try:
        return version("cyberise-downlink")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if pyproject.is_file():
            return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
        return "unknown"


__version__ = _resolve_version()
