"""Log lines as records — the three formats, the traceback, the backwards read and its window."""

import datetime
from pathlib import Path

import pytest

from downlink import logformat

LINES = [
    "INFO 2026-10-06 08:00:00,000 views 1 2 page served",
    "ERROR 2026-10-06 08:05:00,000 views 1 2 it broke",
    "Traceback (most recent call last):",
    '  File "x.py", line 1',
    "WARNING 2026-10-06 08:10:00,000 tasks 1 2 slow",
]


def write_log(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def test_records_carry_their_traceback_and_come_newest_first(tmp_path):
    records = list(logformat.newest_first(write_log(tmp_path / "errors.log", LINES)))

    assert [record.level for record in records] == ["WARNING", "ERROR", "INFO"]
    assert records[1].message.splitlines() == [
        "it broke",
        "Traceback (most recent call last):",
        '  File "x.py", line 1',
    ]


def test_a_missing_file_yields_nothing_never_a_crash(tmp_path):
    assert list(logformat.newest_first(tmp_path / "gone.log")) == []


def test_reading_backwards_survives_block_edges_and_windows_line_ends(tmp_path, monkeypatch):
    """Lines cut by a block boundary are joined again, and a CR before the LF is not part of the message."""
    monkeypatch.setattr(logformat, "BLOCK_BYTES", 7)
    path = tmp_path / "crlf.log"
    path.write_bytes(
        b"INFO 2026-10-06 08:00:00,000 views 1 2 first\r\nERROR 2026-10-06 08:01:00,000 views 1 2 second\r\n"
    )

    assert [record.message for record in logformat.newest_first(path)] == ["second", "first"]


def test_a_plain_line_keeps_its_own_offset(tmp_path):
    path = write_log(tmp_path / "app.log", ["2026-10-06T05:16:15+0200 WARNING reaped dead worker"])

    (record,) = logformat.newest_first(path)

    assert record.when.utcoffset() == datetime.timedelta(hours=2)
    assert (record.level, record.message) == ("WARNING", "reaped dead worker")


def test_a_caddy_json_line_becomes_a_record_with_its_error(tmp_path):
    path = write_log(
        tmp_path / "caddy.log", ['{"level": "warn", "ts": 1791264264.1, "msg": "skipped", "error": "no TLS"}']
    )

    (record,) = logformat.newest_first(path)

    assert (record.level, record.message) == ("WARNING", "skipped: no TLS")


def test_records_since_reads_only_inside_the_window(tmp_path):
    path = write_log(tmp_path / "errors.log", LINES)
    edge = datetime.datetime(2026, 10, 6, 8, 5).astimezone()

    assert [record.level for record in logformat.records_since(path, since=edge)] == ["WARNING", "ERROR"]


def test_a_django_stamp_with_its_offset_is_read_as_that_instant():
    """Django's asctime may carry a UTC offset; a parser blind to it misses every such line."""
    record = logformat.split_line('INFO 2026-10-12 17:07:45+02:00 log 30828 37008 "POST /api/heartbeats/beat" 200 209')

    assert record is not None and record.level == "INFO"
    assert record.when == datetime.datetime(2026, 10, 12, 15, 7, 45, tzinfo=datetime.UTC)
    assert record.message == '"POST /api/heartbeats/beat" 200 209'


def test_a_django_stamp_without_an_offset_is_still_local_time():
    record = logformat.split_line("ERROR 2026-10-06 08:05:00,123 views 1 2 it broke")

    assert record is not None and record.message == "it broke"
    assert record.when == datetime.datetime(2026, 10, 6, 8, 5, 0, 123000).astimezone()


WHEN = datetime.datetime(2026, 10, 31, 12, 32, tzinfo=datetime.UTC)


def test_warnings_and_errors_are_trouble_info_is_not():
    assert logformat.is_trouble(logformat.ReadRecord(WHEN, "WARNING", "slow"))
    assert logformat.is_trouble(logformat.ReadRecord(WHEN, "ERROR", "it broke"))
    assert not logformat.is_trouble(logformat.ReadRecord(WHEN, "INFO", "page served"))


def test_a_routine_warning_is_not_trouble():
    """Caddy's admin socket and its plaintext redirect server warn on every start, by design."""
    for message in (
        "admin endpoint on open interface; host checking disabled",
        "HTTP/2 skipped because it requires TLS",
        "HTTP/3 skipped because it requires TLS",
    ):
        assert not logformat.is_trouble(logformat.ReadRecord(WHEN, "WARNING", message))


def test_a_routine_message_at_error_level_is_still_trouble():
    """The list names warnings checked once — a louder record of the same text is news."""
    assert logformat.is_trouble(logformat.ReadRecord(WHEN, "ERROR", "HTTP/2 skipped because it requires TLS"))


@pytest.mark.parametrize("stamp", ['"inf"', "1e30", "true", '"soon"', "1"])
def test_a_json_line_with_an_unusable_stamp_never_stops_the_reader(tmp_path, stamp):
    """Reading must outlive whatever another program wrote; a stamp no clock can show is not a record."""
    path = write_log(tmp_path / "foreign.log", [f'{{"level": "info", "ts": {stamp}, "msg": "x"}}', *LINES])

    assert [record.level for record in logformat.newest_first(path)][:3] == ["WARNING", "ERROR", "INFO"]
