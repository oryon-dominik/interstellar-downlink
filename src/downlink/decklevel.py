"""The deck's console level: one switch for every process on this machine.

The deck is every process on one machine. A command, or a key on a control surface, writes a
local board; every process reads it again at most once per :data:`RECHECK_SECONDS`. No restart,
no signal between processes: the file is the whole protocol. Processes that log carry
:class:`DeckLevelFilter` on their console handler; processes that print ask :func:`allowed`
before each line.

Two axes, kept apart: the **level** says how bad a line must be to reach any console; a
**focus** says what is being watched right now and sets its own level for one topic: a logger
name or a process's topic, matched as a dotted prefix, the longest match winning. A focus can
open a topic below the deck level or quiet it above.

The caller decides where the board lives: :func:`board` names it under a state directory the
caller knows, and every function here takes that path. Without one there is no board and
everything passes. Its shape, at ``<state>/events/deck-loglevel-<host>.json``::

    {"level": "WARNING", "focus": {"heartbeats": "DEBUG"}, "set_at": "<stamp with offset>"}

NOTICE (25) sits between INFO and WARNING: more than routine, not yet a warning. Importing
this module registers it.

Errors always pass: WARNING is the highest level either axis takes. Log files carry no filter
and keep writing whatever their handlers allow, including the extra lines of a logger a focus
has opened below its own level.
"""

import datetime
import json
import logging
import platform
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

#: More than routine, not yet a warning: the stop between INFO and WARNING.
NOTICE = 25
logging.addLevelName(NOTICE, "NOTICE")
#: What either axis can be set to. ERROR and above always reach the console.
LEVELS = ("DEBUG", "INFO", "NOTICE", "WARNING")
#: The deck level's stops in order, off first; :func:`cycle` walks them.
STEPS = (None, logging.DEBUG, logging.INFO, NOTICE, logging.WARNING)
#: How often a running process looks at the board again, at most.
RECHECK_SECONDS = 1.0


class Setting(NamedTuple):
    """What the board says: the deck level (None leaves each process its own) and the focused topics."""

    level: int | None
    focus: dict[str, int]


EMPTY = Setting(level=None, focus={})


def board(state: Path) -> Path:
    """Return this machine's board under *state*: local, one per host, never committed."""
    return state / "events" / f"deck-loglevel-{platform.node().lower()}.json"


def _number(name: object) -> int | None:
    """Return a level name as a number capped at WARNING; None for anything unreadable or below DEBUG."""
    number = logging.getLevelNamesMapping().get(str(name).strip().upper())
    return None if number is None or number < logging.DEBUG else min(number, logging.WARNING)


def _settable(level: str) -> int:
    """Return a level the switch may take as a number; refuse anything but DEBUG, INFO, NOTICE or WARNING."""
    name = level.strip().upper()
    if name not in LEVELS:
        raise ValueError(f"cannot set {level!r}: choose DEBUG, INFO, NOTICE or WARNING")
    return logging.getLevelNamesMapping()[name]


def read(board_path: Path | None) -> Setting:
    """Read the board; EMPTY when it is absent or unreadable, so a broken file silences nothing."""
    if board_path is None:
        return EMPTY
    try:
        content = json.loads(board_path.read_text(encoding="utf-8"))
        level = _number(content["level"]) if content.get("level") else None
        focus = {str(topic): number for topic, name in content.get("focus", {}).items() if (number := _number(name))}
    except OSError, ValueError, AttributeError, TypeError:
        return EMPTY
    return Setting(level=level, focus=focus)


def _write(board_path: Path, setting: Setting, *, now: datetime.datetime) -> Setting:
    """Store the setting; an empty one removes the board instead of leaving `{}` behind."""
    if setting == EMPTY:
        clear(board_path)
        return EMPTY
    content: dict = {}
    if setting.level is not None:
        content["level"] = logging.getLevelName(setting.level)
    if setting.focus:
        content["focus"] = {topic: logging.getLevelName(number) for topic, number in sorted(setting.focus.items())}
    content["set_at"] = now.isoformat(timespec="seconds")
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(json.dumps(content) + "\n", encoding="utf-8", newline="\n")
    return setting


def set_level(board_path: Path, level: str, *, now: datetime.datetime) -> Setting:
    """Set the deck level; the focus stays as it is. *now* stamps the board, offset included."""
    return _write(board_path, read(board_path)._replace(level=_settable(level)), now=now)


def set_focus(board_path: Path, *, topic: str, level: str, now: datetime.datetime) -> Setting:
    """Give one topic its own level: a logger name or a process's topic, as a dotted prefix."""
    if not topic.strip():
        raise ValueError("a focus needs a topic: a logger name such as heartbeats or app.worker")
    current = read(board_path)
    return _write(board_path, current._replace(focus={**current.focus, topic.strip(): _settable(level)}), now=now)


def drop_focus(board_path: Path, topic: str, *, now: datetime.datetime) -> Setting:
    """Hand one topic back to the deck level."""
    current = read(board_path)
    kept = {name: n for name, n in current.focus.items() if name != topic}
    return _write(board_path, current._replace(focus=kept), now=now)


def cycle(board_path: Path, *, now: datetime.datetime) -> Setting:
    """Move the switch one step: off → DEBUG → INFO → NOTICE → WARNING → off. The focus stays."""
    current = read(board_path)
    following = STEPS[(STEPS.index(current.level) + 1) % len(STEPS)]
    return _write(board_path, current._replace(level=following), now=now)


def clear(board_path: Path) -> None:
    """Remove the board, so every process falls back to its own configuration."""
    board_path.unlink(missing_ok=True)


def threshold(setting: Setting, *, topic: str) -> int | None:
    """Return the level a line from *topic* must reach: the longest matching focus, else the deck level."""
    matches = [name for name in setting.focus if topic == name or topic.startswith(f"{name}.")]
    if matches:
        return setting.focus[max(matches, key=len)]
    return setting.level


def allows(setting: Setting, *, level: int, topic: str) -> bool:
    """Does a line at *level* from *topic* reach the console? Errors always do."""
    bar = threshold(setting, topic=topic)
    return level >= logging.ERROR or bar is None or level >= bar


def allowed(board_path: Path | None, *, level: int, topic: str) -> bool:
    """Should a process print this line? Reads the board fresh, so it suits a few lines a minute."""
    return allows(read(board_path), level=level, topic=topic)


#: Loggers a focus lowered, with the level they had before; shared by every filter in the process.
_opened: dict[str, int] = {}


def _open_focused(setting: Setting) -> None:
    """Lower each logger a focus opens below its own level; restore the ones no focus opens anymore.

    A filter only sees what a logger lets through, so a focus at DEBUG on a logger held
    at INFO would show nothing without this.
    """
    for name, original in list(_opened.items()):
        logging.getLogger(name).setLevel(original)
        del _opened[name]
    for name, number in setting.focus.items():
        logger = logging.getLogger(name)
        if logger.getEffectiveLevel() > number:
            _opened[name] = logger.level
            logger.setLevel(number)


class DeckLevelFilter(logging.Filter):
    """Hold back console lines the deck does not allow; pass everything while no board is set."""

    def __init__(self, board_path: Path | None = None, *, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self.board_path = board_path
        self.clock = clock
        self.setting = read(self.board_path)
        self.checked_at = clock()
        _open_focused(self.setting)

    def filter(self, record: logging.LogRecord) -> bool:
        now = self.clock()
        if now - self.checked_at >= RECHECK_SECONDS:
            self.checked_at = now
            current = read(self.board_path)
            if current != self.setting:
                _open_focused(current)
                self.setting = current
        return allows(self.setting, level=record.levelno, topic=record.name)
