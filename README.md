# downlink

[![prek](https://img.shields.io/badge/prek-enabled-orange?logo=rust&logoColor=white)](https://github.com/j178/prek)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://docs.astral.sh/ruff/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://docs.astral.sh/uv/)
[![python](https://img.shields.io/badge/Python-3.14+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/oryon-dominik/interstellar-downlink/blob/trunk/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/cyberise-downlink)](https://pypi.org/project/cyberise-downlink/)

One log format for every process on a machine: rotating files several processes can share,
uncaught exceptions in the log, one live switch for every console, and a reader for what was
written.

A downlink carries what a spacecraft records back to the ground. This package does the same for
your processes: each one writes the same line, nothing is lost when two of them rotate one
file, and whatever watches the logs reads the lines back as records.

- **Shared files that keep every line.** The standard library's `RotatingFileHandler` loses
  lines when two processes rotate one file. `configure` locks around the rotation.
- **Crashes land in the log.** An uncaught exception, in the process or in a thread, is written
  as CRITICAL with its traceback. The console still shows it. Ctrl+C is not a crash.
- **One console switch, no restart.** Set a level once and every running process follows within
  a second. Errors always get through, and log files keep everything.
- **Stamps carry their offset.** Log lines stay comparable across a daylight saving change.
- **Task lines for Django.** A run reads as one block under the task's name.
- **A reader for all of it.** Read the lines back newest first, Caddy's JSON logs included.

## Install

Requires Python 3.14 or newer. `downlink.tasks` also needs Django 6.0 or newer: take the `django` extra.

```shell
uv add cyberise-downlink
uv add "cyberise-downlink[django]"
```

You install `cyberise-downlink` and import `downlink`. The package named `downlink` on PyPI is a
different project.

## Log to a file

Call `configure` once, early. Calling it again changes nothing, so a loop may call it freely.

```python
from pathlib import Path

import downlink

log = downlink.configure(name="probe", log_file=Path("logs") / "probe.log")
log.info("engines warm")
```

```text
2026-11-05T09:18:31+0100 INFO    engines warm
```

- Each file rotates at 2 MB and keeps three backups.
- The logger stops propagating, so your program's console output stays its own.
- `configure` creates the file's directory, one level deep. If it cannot, it says so on stderr
  and the program runs on without a log file.
- The first `configure` in a process also installs the crash hooks. Without `configure`, call
  `downlink.record_crashes(logger)` yourself.

## Log from Django

```python
import logging

import downlink
from django.utils import timezone
from downlink import decklevel

BOARD = decklevel.board(BASE_DIR / "state")  # see "Switch every console at once"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "()": "downlink.StampFormatter",
            "fmt": downlink.DJANGO_VERBOSE,
            "style": "{",
            "zone": timezone.get_default_timezone,
        },
    },
    "filters": {"deck_level": {"()": "downlink.DeckLevelFilter", "board_path": BOARD}},
    "handlers": {
        "console": {
            "class": "downlink.ConsoleHandler",
            "filters": ["deck_level"],
            "zone": timezone.get_default_timezone,
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
```

Install the crash hooks in an app's `ready`:

```python
downlink.record_crashes(logging.getLogger("shop.crashes"))
```

`StampFormatter` writes the full stamp with its offset for your log files. `ConsoleHandler` draws
the console line: time of day, level in its colour, message. Both take a `zone` callable; leave
it out for the machine's local time. Pass `timezone.get_default_timezone`, not the current
timezone, so a log line keeps the project's clock whoever caused it.

## Switch every console at once

The *deck* is every process on one machine. The *board* is a small JSON file they all read; the
filter looks at it again at most once per second, and only when there is a line to judge. Without
a board, or with an unreadable one, everything passes.

```python
import datetime
from pathlib import Path

from downlink import decklevel

board = decklevel.board(Path("state"))
now = datetime.datetime.now().astimezone()

decklevel.set_level(board, "warning", now=now)                   # quiet every console
decklevel.set_focus(board, topic="shop.worker", level="debug", now=now)  # but watch this one
decklevel.clear(board)                                           # back to each process's own setting
```

The levels are DEBUG, INFO, NOTICE and WARNING. NOTICE (25) sits between INFO and WARNING, and
importing `downlink` registers it. A focus matches a logger name as a dotted prefix, the longest
match winning. Processes that `print` instead of log ask `downlink.allowed(board, level=..., topic=...)`.

## Task lines

`downlink.tasks` replaces Django's own `Task id=… state=…` lines. Every line names the task, and
what the task logs while it runs stands under its name:

```text
send_invoices ○ queued default · every 15 minutes · next 08:18:45
send_invoices ▶ running default
send_invoices │ invoices sent 12 · failed 0
send_invoices ✓ ok 2s
```

```python
INSTALLED_APPS = [..., "downlink.tasks.TaskLines"]
DOWNLINK_TASK_LOGGER_PREFIX = "shop"
```

A logger name is the prefix, the part the process plays and the queue:
`shop.worker.default` for a run, `shop.scheduler.default` for what the scheduler queued,
`shop.tasks.default` for what any other process queued. With
[django-scheduled-tasks](https://pypi.org/project/django-scheduled-tasks/) installed, the
scheduler's line adds the schedule, the lateness and the next run. No other module imports Django.

## Read the logs back

```python
import datetime
from pathlib import Path

import downlink

an_hour_ago = datetime.datetime.now().astimezone() - datetime.timedelta(hours=1)

for record in downlink.records_since(Path("logs") / "probe.log", since=an_hour_ago):
    if downlink.is_trouble(record):
        print(record.when, record.level, record.message)
```

- The reader understands `LINE_FORMAT`, which `configure` writes, `DJANGO_VERBOSE` and Caddy's JSON lines.
- A traceback joins the record it follows.
- It reads the last 4 MiB of one file and does not follow rotated backups.
- `is_trouble` means WARNING and above, minus a few warnings Caddy raises by design.

## Read another program's output

`downlink.pipe.level_and_message(line)` reads the level of a line another program wrote, so you
can forward it to a logger:

```python
from downlink import pipe

log.log(*pipe.level_and_message("Error: address in use"))
```

## Develop

```shell
just install   # dependencies, hooks
just test
just lint
just build     # the wheel
```
