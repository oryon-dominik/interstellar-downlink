"""The deck's console level: one switch for every process on this machine."""

import datetime
import json
import logging
from pathlib import Path

import pytest

from downlink import decklevel

NOW = datetime.datetime(2026, 11, 2, 9, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))


def _record(level: int, name: str = "deck") -> logging.LogRecord:
    """A bare record at *level* from logger *name*."""
    return logging.LogRecord(name, level, __file__, 1, "line", None, None)


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds


@pytest.fixture
def board(tmp_path: Path) -> Path:
    """A board path nobody has written yet."""
    return tmp_path / "deck-loglevel-apollon.json"


def test_without_a_board_every_line_passes(board: Path):
    """No switch set means the pane shows what its own configuration lets through."""
    gate = decklevel.DeckLevelFilter(board_path=board)

    assert gate.filter(_record(logging.DEBUG)) is True


def test_a_set_level_holds_back_what_lies_below_it(board: Path):
    """WARNING on the board keeps INFO off the console and lets WARNING through."""
    decklevel.set_level(board, "warning", now=NOW)
    gate = decklevel.DeckLevelFilter(board_path=board)

    assert gate.filter(_record(logging.INFO)) is False
    assert gate.filter(_record(logging.WARNING)) is True


def test_errors_always_reach_the_console(board: Path):
    """Distress is never switched off — a hand-edited board above WARNING is read as WARNING."""
    board.write_text(json.dumps({"level": "CRITICAL", "focus": {"deck": "CRITICAL"}}), encoding="utf-8", newline="\n")
    gate = decklevel.DeckLevelFilter(board_path=board)

    assert gate.filter(_record(logging.ERROR)) is True
    assert gate.filter(_record(logging.WARNING)) is True


@pytest.mark.parametrize("level", ["error", "loud", ""])
def test_a_level_that_would_silence_distress_or_means_nothing_is_refused(board: Path, level: str):
    """Only DEBUG, INFO, NOTICE and WARNING can be set: nothing that hides an error, nothing unreadable."""
    with pytest.raises(ValueError, match="DEBUG, INFO, NOTICE or WARNING"):
        decklevel.set_level(board, level, now=NOW)
    with pytest.raises(ValueError, match="DEBUG, INFO, NOTICE or WARNING"):
        decklevel.set_focus(board, topic="heartbeats", level=level, now=NOW)


def test_an_unreadable_board_silences_nothing(board: Path):
    """A broken file must not blank every console."""
    board.write_text("{not json", encoding="utf-8", newline="\n")
    gate = decklevel.DeckLevelFilter(board_path=board)

    assert gate.filter(_record(logging.DEBUG)) is True


def test_a_change_reaches_a_running_pane_within_the_recheck(board: Path):
    """Live, no restart: the board is read again once the recheck interval passed."""
    clock = Clock()
    gate = decklevel.DeckLevelFilter(board_path=board, clock=clock)
    assert gate.filter(_record(logging.INFO)) is True

    decklevel.set_level(board, "WARNING", now=NOW)
    assert gate.filter(_record(logging.INFO)) is True  # still inside the interval

    clock.seconds += decklevel.RECHECK_SECONDS
    assert gate.filter(_record(logging.INFO)) is False


def test_clear_returns_the_deck_to_each_pane_s_own_configuration(board: Path):
    """Clearing removes the board — and clearing an absent one is no error."""
    decklevel.set_level(board, "INFO", now=NOW)
    decklevel.set_focus(board, topic="shop", level="DEBUG", now=NOW)

    decklevel.clear(board)
    decklevel.clear(board)

    assert decklevel.read(board) == decklevel.EMPTY
    assert not board.exists()


def test_the_board_carries_level_focus_and_an_offset_stamp(board: Path):
    """The stored stamp carries its offset."""
    decklevel.set_level(board, "info", now=NOW)
    decklevel.set_focus(board, topic="heartbeats", level="debug", now=NOW)

    written = json.loads(board.read_text(encoding="utf-8"))
    assert written["level"] == "INFO"
    assert written["focus"] == {"heartbeats": "DEBUG"}
    assert written["set_at"] == "2026-11-02T09:30:00+01:00"


def test_the_board_lives_under_the_state_directory_per_host(monkeypatch, tmp_path: Path):
    """A local notice board among the events of a state directory the caller names."""
    monkeypatch.setattr("platform.node", lambda: "APOLLON")

    path = decklevel.board(tmp_path)

    assert path == tmp_path / "events" / "deck-loglevel-apollon.json"


# -- focus ---------------------------------------------------------------------


def test_focus_opens_one_topic_below_the_deck_level(board: Path):
    """Deck at WARNING, heartbeats focused at DEBUG: heartbeat detail shows, the rest stays quiet."""
    decklevel.set_level(board, "WARNING", now=NOW)
    decklevel.set_focus(board, topic="heartbeats", level="DEBUG", now=NOW)
    setting = decklevel.read(board)

    assert decklevel.allows(setting, level=logging.DEBUG, topic="heartbeats") is True
    assert decklevel.allows(setting, level=logging.DEBUG, topic="heartbeats.alarms") is True
    assert decklevel.allows(setting, level=logging.INFO, topic="hooks") is False


def test_focus_can_also_quiet_one_topic(board: Path):
    """Deck at DEBUG, one chatty topic held at WARNING."""
    decklevel.set_level(board, "DEBUG", now=NOW)
    decklevel.set_focus(board, topic="shop.worker", level="WARNING", now=NOW)
    setting = decklevel.read(board)

    assert decklevel.allows(setting, level=logging.INFO, topic="shop.worker") is False
    assert decklevel.allows(setting, level=logging.INFO, topic="shop.web") is True


def test_the_longest_focus_wins(board: Path):
    """A narrower topic overrides a wider one — `heartbeatsx` is no child of `heartbeats`."""
    decklevel.set_focus(board, topic="shop", level="WARNING", now=NOW)
    decklevel.set_focus(board, topic="shop.worker", level="DEBUG", now=NOW)
    setting = decklevel.read(board)

    assert decklevel.threshold(setting, topic="shop.worker.orders") == logging.DEBUG
    assert decklevel.threshold(setting, topic="shop.web") == logging.WARNING
    assert decklevel.threshold(setting, topic="shopfloor") is None


def test_dropping_the_last_focus_without_a_level_removes_the_board(board: Path):
    """An empty setting is no setting — the file goes rather than lingering as `{}`."""
    decklevel.set_focus(board, topic="heartbeats", level="DEBUG", now=NOW)

    decklevel.drop_focus(board, "heartbeats", now=NOW)

    assert not board.exists()


def test_a_focus_lower_than_the_logger_opens_the_logger_and_closes_it_again(board: Path):
    """A logger held at INFO cannot say DEBUG — focus lowers it, and dropping focus restores it."""
    logger = logging.getLogger("decklevel.probe")
    logger.setLevel(logging.INFO)
    clock = Clock()
    gate = decklevel.DeckLevelFilter(board_path=board, clock=clock)

    decklevel.set_focus(board, topic="decklevel.probe", level="DEBUG", now=NOW)
    clock.seconds += decklevel.RECHECK_SECONDS
    gate.filter(_record(logging.INFO))
    opened = logger.level

    decklevel.drop_focus(board, "decklevel.probe", now=NOW)
    clock.seconds += decklevel.RECHECK_SECONDS
    gate.filter(_record(logging.INFO))

    assert opened == logging.DEBUG
    assert logger.level == logging.INFO


# -- the switch key and the printing processes ---------------------------------


def test_cycle_walks_every_stop_and_back_to_off(board: Path):
    """One press, one step through off, DEBUG, INFO, NOTICE, WARNING; the focus survives."""
    decklevel.set_focus(board, topic="heartbeats", level="DEBUG", now=NOW)

    steps = [decklevel.cycle(board, now=NOW).level for _ in range(5)]

    assert steps == [logging.DEBUG, logging.INFO, decklevel.NOTICE, logging.WARNING, None]
    assert decklevel.read(board).focus == {"heartbeats": logging.DEBUG}


def test_a_printed_line_asks_the_deck_by_level_and_topic(board: Path):
    """Processes that print instead of log ask the board before each line."""
    decklevel.set_level(board, "WARNING", now=NOW)
    decklevel.set_focus(board, topic="shop.worker", level="INFO", now=NOW)

    assert decklevel.allowed(board, level=logging.INFO, topic="shop.worker") is True
    assert decklevel.allowed(board, level=logging.INFO, topic="shop.web") is False
    assert decklevel.allowed(board, level=logging.ERROR, topic="shop.web") is True


# -- the command ---------------------------------------------------------------


def test_a_board_below_debug_reads_as_unset_and_the_key_still_steps(board: Path):
    """A hand-edited NOTSET is no stop on the fader — read as unset, `l` steps on to DEBUG instead of crashing."""
    board.write_text(json.dumps({"level": "NOTSET"}), encoding="utf-8", newline="\n")

    assert decklevel.read(board).level is None
    assert decklevel.cycle(board, now=NOW).level == logging.DEBUG


# -- NOTICE --------------------------------------------------------------------


def test_notice_sits_between_info_and_warning_and_is_named():
    """25 — more than routine, not yet a warning; every process that imports the deck knows its name."""
    assert logging.INFO < decklevel.NOTICE < logging.WARNING
    assert logging.getLevelName(decklevel.NOTICE) == "NOTICE"


def test_a_notice_deck_shows_notices_and_holds_back_routine(board: Path):
    """At NOTICE the pane keeps what matters now and drops the INFO chatter."""
    decklevel.set_level(board, "notice", now=NOW)
    setting = decklevel.read(board)

    assert json.loads(board.read_text(encoding="utf-8"))["level"] == "NOTICE"
    assert decklevel.allows(setting, level=decklevel.NOTICE, topic="shop.worker.orders") is True
    assert decklevel.allows(setting, level=logging.INFO, topic="shop.worker.chores") is False


def test_without_a_board_path_nothing_is_filtered():
    """A production web node has no board: its logging must run, unfiltered, not crash."""
    gate = decklevel.DeckLevelFilter()

    assert gate.filter(logging.LogRecord("shop", logging.DEBUG, __file__, 1, "line", None, None)) is True
    assert decklevel.allowed(None, level=logging.DEBUG, topic="shop") is True
