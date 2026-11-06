"""The console line: time of day, level, message, the same for every process.

One handler draws it, so a development server, a worker, a command-line tool and another program
whose level :mod:`downlink.pipe` reads look alike side by side. There is no path column: the files
carry the module, and a narrow pane needs the width for the message.
"""

import datetime
import logging

from rich.console import Console, ConsoleRenderable
from rich.logging import RichHandler
from rich.text import Text
from rich.theme import Theme

from downlink import stamps
from downlink.decklevel import NOTICE

#: Rich colours the standard levels; NOTICE is downlink's own and needs a colour of its own.
THEME = Theme({f"logging.level.{logging.getLevelName(NOTICE).lower()}": "cyan"})


class ConsoleHandler(RichHandler):
    """Rich's log line in downlink's shape: the time of day in *zone*, on every line.

    In a logging configuration it takes the class form, which passes every other key on:
    ``{"class": "downlink.ConsoleHandler", "zone": "ext://django.utils.timezone.get_default_timezone"}``.
    """

    def __init__(
        self,
        level: int | str = logging.NOTSET,
        *,
        zone: stamps.Zone | None = None,
        console: Console | None = None,
        **options,
    ) -> None:
        if console is None:
            console = Console(theme=THEME)
        else:
            console.push_theme(THEME)

        def time_of_day(moment: datetime.datetime) -> Text:
            return Text(stamps.clock(moment, zone=zone))

        super().__init__(
            level,
            console=console,
            log_time_format=time_of_day,
            omit_repeated_times=False,
            show_path=False,
            **options,
        )

    def render_message(self, record: logging.LogRecord, message: str) -> ConsoleRenderable:
        """Return the message, set under its task's name when a running task wrote it."""
        if task := getattr(record, "running_task", None):
            message = f"{task} │ {message}"
        return super().render_message(record, message)
