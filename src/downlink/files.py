"""One rotating log file per command-line tool: local, never committed.

A tool sets up its logger through :func:`configure` rather than building its own handler, so
the format, the rotation limits and the rule that the console stays the tool's own are the same
in every process.

The handler locks. Two processes share these files by design, and the standard library's
``RotatingFileHandler`` loses lines when two processes rotate one file: the loser of the rename
cascade raises and the record is dropped. Two writers lost about 85 percent of 800 lines that
way. ``ConcurrentRotatingFileHandler`` takes a file lock around the rotation, the one thing that
cannot be arranged without coordination.
"""

import logging
import sys
from pathlib import Path

from concurrent_log_handler import ConcurrentRotatingFileHandler

from downlink import crashlog, logformat

# 2 MB × 3 backups keeps recent history without ever growing unbounded.
MAX_BYTES = 2_000_000
BACKUP_COUNT = 3

#: Whether this process's exception hooks are installed; the first configure installs them, once.
_hooked = False


def configure(*, name: str, log_file: Path, level: str = "INFO", library: str | None = None) -> logging.Logger:
    """Give a logger one rotating file handler; calling it again changes nothing.

    A repeat call attaches no second handler, so a serve loop may call it per tick, and a logger
    already set up keeps its file. Propagation is cut: the console belongs to the tool's own
    output, not to log records.

    A missing directory is created one level deep, never more. If the file cannot be prepared,
    the reason goes to stderr, the logger comes back without a file, and the run goes on.

    The first call in a process installs the exception hooks, so a process or thread that dies
    leaves its traceback in this file. The *library* logger family gets this file too, unless it
    already has a handler, so warnings from shared helpers land in the caller's log and not raw
    on stderr.
    """
    global _hooked
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level.upper())
    logger.propagate = False
    try:
        # One level only: `parents=True` would create a mistyped root right here, and every
        # health check downstream would then find the root it had just invented.
        log_file.parent.mkdir(exist_ok=True)
        # Present from the start: the handler opens lazily, and a log directory that lists
        # only the tools that happened to run reads as if the others were missing.
        log_file.touch(exist_ok=True)
    except OSError as error:
        # Straight to stderr: the logger this message is about is the one that just failed.
        print(f"{name}: no log: {log_file} could not be prepared ({error})", file=sys.stderr)
        logger.addHandler(logging.NullHandler())
        return logger
    handler = ConcurrentRotatingFileHandler(log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter(logformat.LINE_FORMAT, datefmt=logformat.DATE_FORMAT))
    logger.addHandler(handler)
    if library is not None and not (shared := logging.getLogger(library)).handlers:
        shared.setLevel(level.upper())
        shared.propagate = False
        shared.addHandler(handler)
    if not _hooked:
        _hooked = True
        crashlog.record_crashes(logger)
    return logger
