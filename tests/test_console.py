"""The console line: time of day, level, message, the same for every process."""

import datetime
import io
import logging
import zoneinfo

from rich.console import Console

import downlink

BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")
SUMMER = datetime.datetime(2026, 9, 25, 9, 56, 50, tzinfo=datetime.UTC)


def berlin() -> datetime.tzinfo:
    """The zone a caller hands in."""
    return BERLIN


def _rendered(handler: logging.Handler, *, level: int = logging.INFO, message: str = "docked") -> str:
    record = logging.LogRecord("shop", level, __file__, 1, message, None, None)
    record.created = SUMMER.timestamp()
    handler.handle(record)
    return handler.console.file.getvalue()  # type: ignore[attr-defined]  # a ConsoleHandler on a StringIO


def _plain() -> Console:
    return Console(file=io.StringIO(), width=80, color_system=None)


def test_a_line_reads_time_of_day_level_and_message():
    line = _rendered(downlink.ConsoleHandler(zone=berlin, console=_plain()))
    assert line.split() == ["11:56:50", "INFO", "docked"]


def test_a_line_carries_no_path_column():
    line = _rendered(downlink.ConsoleHandler(zone=berlin, console=_plain()))
    assert "test_console.py" not in line


def test_every_line_keeps_its_time_even_when_it_repeats():
    handler = downlink.ConsoleHandler(zone=berlin, console=_plain())
    _rendered(handler)
    lines = _rendered(handler).splitlines()
    assert all(line.startswith("11:56:50") for line in lines)


def test_the_notice_level_has_a_colour_of_its_own():
    console = Console(file=io.StringIO(), width=80, color_system="truecolor", force_terminal=True)
    line = _rendered(downlink.ConsoleHandler(zone=berlin, console=console), level=downlink.NOTICE)
    _, _, after_time = line.partition("11:56:50")
    styled, _, _ = after_time.partition("NOTICE")
    assert "\x1b[" in styled


def test_a_running_task_s_line_stands_under_its_name():
    record = logging.LogRecord("shop.commands", logging.INFO, __file__, 1, "sent 0", None, None)
    record.running_task = "send_invoices"
    handler = downlink.ConsoleHandler(zone=berlin, console=_plain())
    handler.handle(record)
    assert "send_invoices │ sent 0" in handler.console.file.getvalue()  # type: ignore[attr-defined]


def test_a_line_outside_any_run_stands_alone():
    assert "│" not in _rendered(downlink.ConsoleHandler(zone=berlin, console=_plain()))
