"""Another program's output: the level read, the message kept."""

import logging

import pytest

from downlink import pipe


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("1730540000: mosquitto version 2.1.2 running", (logging.INFO, "mosquitto version 2.1.2 running")),
        ("1730540000: Error: Address in use", (logging.ERROR, "Error: Address in use")),
        ("Warning: no tailwind config", (logging.WARNING, "Warning: no tailwind config")),
        ("Done in 41ms", (logging.INFO, "Done in 41ms")),
        ('{"level": "error", "ts": 1791264264.1, "msg": "tls failed"}', (logging.ERROR, "tls failed")),
        ("2026-10-06T05:16:15+0200 WARNING lease lost", (logging.WARNING, "lease lost")),
        # tailwind colours its own words; the console line brings the colour.
        ("Done in \x1b[33m597ms\x1b[39m", (logging.INFO, "Done in 597ms")),
        ("\x1b[31mError\x1b[39m: CssSyntaxError", (logging.ERROR, "Error: CssSyntaxError")),
    ],
)
def test_a_line_keeps_its_message_and_gets_its_level(line, expected):
    assert pipe.level_and_message(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        '{"ts": 1791264264.1, "msg": "no level"}',
        '{"level": "trace", "ts": 1791264264.1, "msg": "unknown level"}',
        "GET 2026-10-06 08:05:00 x",
        "2026-10-06T05:16:15+0200 HTTP request",
    ],
)
def test_a_level_logging_does_not_know_reads_as_info(line):
    """`Logger.log` refuses anything but a number, so the level is always one."""
    level, _ = pipe.level_and_message(line)

    assert level == logging.INFO
