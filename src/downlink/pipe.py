"""Read the level of a line another program wrote: a broker, a web server, a watcher.

A program that is not Python writes in a format of its own. A caller that pipes it onto the
console line asks here which level each line carries: a format downlink reads, a leading level
word, else INFO.
"""

import logging
import re

from downlink import logformat

#: A terminal colour or style code: CSI sequences, as tailwind and most command-line tools write them.
ANSI_CODE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
#: Mosquitto's prefix, epoch seconds and a colon; the console line's own stamp replaces it.
EPOCH_PREFIX = re.compile(r"^\d{9,}:\s*")
#: A line that opens with its level: `Error:`, `warning`, `[ERROR]`.
LEADING_LEVEL = re.compile(r"^\[?(?P<level>error|warning|warn|critical|fatal|panic)\b", re.IGNORECASE)


def _number(name: str) -> int:
    return logging.getLevelNamesMapping().get(name, logging.INFO)


def level_and_message(line: str) -> tuple[int, str]:
    """Return the level and message of one line: a format downlink reads, a leading level word, else INFO.

    The line's own colour codes go first: the console line colours by level, and a code in
    front of `Error` would hide the level from the reading. A level logging does not know reads
    as INFO, so the result always suits ``Logger.log``.
    """
    line = ANSI_CODE.sub("", line)
    if (record := logformat.split_line(line)) is not None:
        return _number(record.level), record.message
    message = EPOCH_PREFIX.sub("", line.strip())
    if match := LEADING_LEVEL.match(message):
        name = logformat.LEVEL_ALIASES.get(match["level"].upper(), match["level"].upper())
        return _number(name), message
    return logging.INFO, message
