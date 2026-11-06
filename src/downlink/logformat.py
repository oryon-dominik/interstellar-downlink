"""Log lines as records: three formats, read back from the end of a file.

The writing half names its formats here too, so a writer and its reader can never drift
apart: :data:`LINE_FORMAT` with :data:`DATE_FORMAT` for a command-line tool's file,
:data:`DJANGO_VERBOSE` for a Django project's files. Caddy's JSON lines are only read.

    Django verbose   ERROR 2026-10-06 08:05:00+02:00 module pid tid message
    plain            2026-10-06T05:16:15+0200 WARNING message
    JSON             {"level": "error", "ts": 1791264264.1, "msg": "..."}  (Caddy)

A Django stamp without an offset reads as local time. A line in none of the formats continues
the record above it (a traceback). Every record carries its offset.
"""

import datetime
import json
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

#: A command-line tool's file: ISO stamp with offset, padded level, message; %-style.
LINE_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
#: A Django project's files, {-style; the project's formatter class writes asctime with its offset.
DJANGO_VERBOSE = "{levelname} {asctime} {module} {process:d} {thread:d} {message}"
#: How far back from the end one read goes; older entries are grep's job.
TAIL_BYTES = 4 * 1024 * 1024
BLOCK_BYTES = 64 * 1024
ERROR_LEVELS = ("ERROR", "CRITICAL")
TROUBLE_LEVELS = ("WARNING", *ERROR_LEVELS)
#: Spellings other writers use for the standard levels.
LEVEL_ALIASES = {"WARN": "WARNING", "FATAL": "CRITICAL", "PANIC": "CRITICAL"}
#: Warnings Caddy raises by design; every trouble reader drops them.
#: Caddy warns on an admin address that is not localhost, even when it is a unix socket behind
#: filesystem permissions. Its HTTP->HTTPS redirect server warns twice per bound address, out of
#: reach of its `servers` option.
ROUTINE = frozenset(
    {
        "admin endpoint on open interface; host checking disabled",
        "HTTP/2 skipped because it requires TLS",
        "HTTP/3 skipped because it requires TLS",
    }
)


class ReadRecord(NamedTuple):
    """One entry read back from a log; `when` always carries an offset."""

    when: datetime.datetime
    level: str
    message: str


def lines_newest_first(path: Path, *, max_bytes: int = TAIL_BYTES) -> Iterator[str]:
    """Yield the file's lines from the end backwards, in blocks: ten lines cost one block.

    Stops at *max_bytes* from the end; a line cut by that window is dropped. An unreadable
    file yields nothing.
    """
    try:
        handle = path.open("rb")
    except OSError:
        return
    with handle:
        end = handle.seek(0, 2)
        floor = max(0, end - max_bytes)
        position, carry = end, b""
        while position > floor:
            step = min(BLOCK_BYTES, position - floor)
            position -= step
            handle.seek(position)
            pieces = (handle.read(step) + carry).split(b"\n")
            carry = pieces[0]
            for piece in reversed(pieces[1:]):
                yield piece.decode("utf-8", errors="replace").rstrip("\r")
        if floor == 0 and carry:
            yield carry.decode("utf-8", errors="replace").rstrip("\r")


def _level(raw: str) -> str:
    level = raw.strip().upper()
    return LEVEL_ALIASES.get(level, level)


def _django(line: str) -> ReadRecord | None:
    # asctime is date and time, with its UTC offset where a project writes one, else naive local time.
    level, _, rest = line.partition(" ")
    if not level.isupper():
        return None
    date, _, rest = rest.partition(" ")
    clock, _, rest = rest.partition(" ")
    try:
        when = datetime.datetime.fromisoformat(f"{date} {clock}")
    except ValueError:
        return None
    parts = rest.split(" ", 3)  # module pid tid message
    message = parts[3] if len(parts) == 4 else rest
    return ReadRecord(when=when if when.tzinfo else when.astimezone(), level=_level(level), message=message.strip())


def _plain(line: str) -> ReadRecord | None:
    stamp, _, rest = line.partition(" ")
    level, _, message = rest.lstrip().partition(" ")
    if "T" not in stamp or not level.isupper():
        return None
    try:
        when = datetime.datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    return ReadRecord(when=when, level=_level(level), message=message.strip())


def _json(line: str) -> ReadRecord | None:
    if not line.startswith("{"):
        return None
    try:
        entry = json.loads(line)
        when = datetime.datetime.fromtimestamp(float(entry["ts"])).astimezone()
    except ValueError, KeyError, TypeError, OverflowError, OSError:
        # OverflowError and OSError: a stamp the platform's clock cannot show.
        return None
    message = str(entry.get("msg", ""))
    if entry.get("error"):
        message = f"{message}: {entry['error']}"
    return ReadRecord(when=when, level=_level(str(entry.get("level", ""))), message=message)


def split_line(line: str) -> ReadRecord | None:
    """Parse one line in whichever format it is written; None for a continuation line."""
    for parse in (_django, _plain, _json):
        if (record := parse(line)) is not None:
            return record
    return None


def newest_first(path: Path) -> Iterator[ReadRecord]:
    """Yield records from the end of the file backwards; a traceback joins the record it follows.

    Continuations arrive before their record when reading backwards, so they wait for it;
    the ones left over at the window's cut belong to a record outside it and are dropped.
    Reads this one file, not its rotated backups.
    """
    waiting: list[str] = []
    for line in lines_newest_first(path):
        if not line:
            continue
        record = split_line(line)
        if record is None:
            waiting.append(line)
            continue
        if waiting:
            record = record._replace(message="\n".join([record.message, *reversed(waiting)]))
            waiting = []
        yield record


def records_since(path: Path, *, since: datetime.datetime) -> Iterator[ReadRecord]:
    """Yield records stamped at or after *since*, newest first; reading stops at the first older one.

    *since* must carry an offset, like every record. A log is written in time order, so the window
    edge is where reading ends.
    """
    for record in newest_first(path):
        if record.when < since:
            return
        yield record


def is_trouble(record: ReadRecord) -> bool:
    """Is this a warning or error someone has to look at, not one of the `ROUTINE` warnings?"""
    if record.level == "WARNING" and record.message in ROUTINE:
        return False
    return record.level in TROUBLE_LEVELS
