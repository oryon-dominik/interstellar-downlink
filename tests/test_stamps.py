"""Log stamps — the full stamp with its offset in a file, the time of day on a console, in the zone handed in."""

import datetime
import functools
import logging
import logging.config
import zoneinfo

import downlink
from downlink import logformat

SUMMER = datetime.datetime(2026, 9, 25, 9, 56, 50, tzinfo=datetime.UTC)
BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")


def berlin() -> datetime.tzinfo:
    """The zone a Django project's `get_default_timezone` would answer."""
    return BERLIN


def test_the_stamp_reads_date_time_and_offset_in_the_zone_handed_in():
    assert downlink.stamp(SUMMER, zone=berlin) == "2026-09-25 11:56:50+02:00"


def test_the_clock_reads_the_time_of_day_only():
    assert downlink.clock(SUMMER, zone=berlin) == "11:56:50"


def test_without_a_zone_the_machine_clock_decides_and_the_offset_stays():
    assert downlink.stamp(SUMMER) == SUMMER.astimezone().isoformat(sep=" ", timespec="seconds")


def test_a_naive_moment_reads_as_local_time_as_rich_hands_it_over():
    naive_local = SUMMER.astimezone().replace(tzinfo=None)

    assert downlink.clock(naive_local, zone=berlin) == "11:56:50"


def _record(created: float) -> logging.LogRecord:
    record = logging.LogRecord("shop", logging.ERROR, __file__, 1, "lost contact", None, None)
    record.created = created
    return record


def test_the_formatter_writes_the_stamp_into_asctime_and_the_reader_takes_it_back():
    """Writer and reader meet: a verbose line stamped here is read back with its offset."""
    formatter = downlink.StampFormatter(downlink.DJANGO_VERBOSE, style="{", zone=berlin)

    line = formatter.format(_record(SUMMER.timestamp()))
    record = logformat.split_line(line)

    assert line.startswith("ERROR 2026-09-25 11:56:50+02:00 ")
    assert record.when == SUMMER
    assert record.message == "lost contact"


def test_a_logging_configuration_hands_the_zone_through_the_factory_form():
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "verbose": {
                    "()": "downlink.StampFormatter",
                    "fmt": downlink.DJANGO_VERBOSE,
                    "style": "{",
                    "zone": berlin,
                }
            },
            "handlers": {"probe": {"class": "logging.NullHandler", "formatter": "verbose"}},
            "loggers": {"downlink-stamps": {"handlers": ["probe"]}},
        }
    )

    formatter = logging.getLogger("downlink-stamps").handlers[0].formatter

    assert formatter.zone is berlin
    assert formatter.formatTime(_record(SUMMER.timestamp())) == "2026-09-25 11:56:50+02:00"


def test_the_clock_serves_as_a_console_time_format():
    """What Rich's `log_time_format` calls: a moment in, the time of day out."""
    time_format = functools.partial(downlink.clock, zone=berlin)

    assert time_format(SUMMER.astimezone().replace(tzinfo=None)) == "11:56:50"
