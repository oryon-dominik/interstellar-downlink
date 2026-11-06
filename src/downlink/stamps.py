"""Log stamps with their offset: the full stamp in a file, the time of day on a console.

The caller chooses the zone and passes it as a callable. A Django project passes
``django.utils.timezone.get_default_timezone``: its ``TIME_ZONE``, never a zone a request
activated, so a log line keeps the project's clock whoever caused it. A command-line tool
passes nothing and gets the machine's local clock.

A naive moment reads as the machine's local time, which is what ``time.time()`` and Rich
hand over.
"""

import datetime
import logging
from collections.abc import Callable
from typing import Literal

type Zone = Callable[[], datetime.tzinfo]


def _zoned(moment: datetime.datetime, zone: Zone | None) -> datetime.datetime:
    return moment.astimezone(zone() if zone else None)


def stamp(moment: datetime.datetime, *, zone: Zone | None = None) -> str:
    """Return the full stamp, `2026-09-25 11:56:50+02:00`, as a log file keeps it."""
    return _zoned(moment, zone).isoformat(sep=" ", timespec="seconds")


def clock(moment: datetime.datetime, *, zone: Zone | None = None) -> str:
    """Return the time of day, `11:56:50`: a console is read live, and the full stamp wraps a narrow pane."""
    return _zoned(moment, zone).strftime("%H:%M:%S")


class StampFormatter(logging.Formatter):
    """A formatter whose `asctime` is the full stamp in *zone* instead of a zoneless local time.

    In a logging configuration it takes the factory form, which passes every other key on:
    ``{"()": "downlink.StampFormatter", "fmt": downlink.DJANGO_VERBOSE, "style": "{", "zone": ...}``.
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        *,
        zone: Zone | None = None,
    ):
        super().__init__(fmt, datefmt, style)
        self.zone = zone

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return stamp(datetime.datetime.fromtimestamp(record.created, tz=datetime.UTC), zone=self.zone)
