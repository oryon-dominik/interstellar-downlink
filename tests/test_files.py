"""One rotating log file per command-line tool: format, rotation, the crash hooks on the first call."""

import logging
import logging.config
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from concurrent_log_handler import ConcurrentRotatingFileHandler

import downlink
from downlink import files, logformat


def _release(root: Path) -> None:
    """Close every handler holding a file under *root* — Windows cannot remove an open file."""
    for logger in [logging.root, *logging.root.manager.loggerDict.values()]:
        for handler in list(getattr(logger, "handlers", [])):
            if Path(getattr(handler, "baseFilename", "") or "/").is_relative_to(root):
                logger.removeHandler(handler)
                handler.close()


@pytest.fixture(autouse=True)
def fresh_process(tmp_path, monkeypatch):
    """Each test configures as the first tool of a new process, and lets go of its files after."""
    monkeypatch.setattr(files, "_hooked", False)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    yield
    _release(tmp_path)


def _flushed(logger: logging.Logger, log_file: Path) -> str:
    """The file's text once every handler has written out."""
    for handler in logger.handlers:
        handler.flush()
    return log_file.read_text(encoding="utf-8")


def test_configure_writes_to_the_file(tmp_path):
    log_file = tmp_path / "logs" / "x.log"
    logger = downlink.configure(name="downlink-writes", log_file=log_file)

    logger.info("engines warm")

    assert "engines warm" in _flushed(logger, log_file)


def test_configure_is_idempotent(tmp_path):
    logger = downlink.configure(name="downlink-idempotent", log_file=tmp_path / "a.log")
    downlink.configure(name="downlink-idempotent", log_file=tmp_path / "b.log")

    assert len(logger.handlers) == 1


def test_configure_rotates_with_the_locking_handler(tmp_path):
    """Two processes share these files, and the standard library's handler destroys their lines."""
    logger = downlink.configure(name="downlink-rotates", log_file=tmp_path / "x.log")

    handler = logger.handlers[0]
    assert isinstance(handler, ConcurrentRotatingFileHandler)
    assert (handler.maxBytes, handler.backupCount) == (files.MAX_BYTES, files.BACKUP_COUNT)


def test_configure_keeps_the_console_clean_and_honours_the_level(tmp_path):
    """No propagation: the tool owns its console output."""
    logger = downlink.configure(name="downlink-console", log_file=tmp_path / "x.log", level="warning")

    assert logger.propagate is False
    assert logger.level == logging.WARNING


def test_a_written_line_reads_back_as_the_record_it_was(tmp_path):
    """Writer and reader share one format — a changed writer cannot leave the reader behind."""
    log_file = tmp_path / "x.log"
    logger = downlink.configure(name="downlink-roundtrip", log_file=log_file)

    logger.warning("pressure low")
    _flushed(logger, log_file)

    record = next(logformat.newest_first(log_file))
    assert (record.level, record.message) == ("WARNING", "pressure low")
    assert record.when.tzinfo is not None


def test_a_django_verbose_line_reads_back_as_its_record():
    """The verbose format, with an offset the way a project's formatter writes asctime."""
    formatter = logging.Formatter(logformat.DJANGO_VERBOSE, style="{")
    formatter.formatTime = lambda record, datefmt=None: "2026-11-02 09:30:00+01:00"
    line = formatter.format(logging.LogRecord("shop", logging.ERROR, __file__, 1, "lost contact", None, None))

    record = logformat.split_line(line)

    assert (record.level, record.message) == ("ERROR", "lost contact")
    assert record.when.isoformat() == "2026-11-02T09:30:00+01:00"


def test_a_root_that_does_not_exist_is_never_invented(tmp_path, capsys):
    """A missing root stays missing — and says so on stderr; the run goes on without a file."""
    logger = downlink.configure(name="downlink-ghost", log_file=tmp_path / "ghost" / "logs" / "x.log")

    assert not (tmp_path / "ghost").exists()
    assert "downlink-ghost" in capsys.readouterr().err
    assert logger.propagate is False


def test_the_library_family_warns_into_the_file_of_its_caller(tmp_path, capfd):
    """Shared helpers without a handler print raw on stderr; their warnings belong in the caller's file."""
    library = logging.getLogger("downlink-test-library")
    log_file = tmp_path / "caller.log"
    downlink.configure(name="downlink-caller", log_file=log_file, library=library.name)

    logging.getLogger("downlink-test-library.processes").warning("cannot kill %s", 4711)

    assert "cannot kill 4711" in _flushed(library, log_file)
    assert "cannot kill" not in capfd.readouterr().err


def test_a_process_that_dies_leaves_its_traceback_in_the_file(tmp_path, monkeypatch):
    passed_on = []
    monkeypatch.setattr(sys, "excepthook", lambda *crash: passed_on.append(crash))
    log_file = tmp_path / "worker.log"
    logger = downlink.configure(name="downlink-worker", log_file=log_file)

    crash = (RuntimeError, RuntimeError("database is locked"), None)
    sys.excepthook(*crash)

    written = _flushed(logger, log_file)
    assert "CRITICAL" in written
    assert "RuntimeError: database is locked" in written
    assert passed_on == [crash]


def test_only_the_first_arm_takes_the_hooks(tmp_path):
    """A second tool in the same process must not chain a second hook."""
    before = sys.excepthook
    downlink.configure(name="downlink-first", log_file=tmp_path / "first.log")
    taken = sys.excepthook
    downlink.configure(name="downlink-second", log_file=tmp_path / "second.log")

    assert taken is not before
    assert sys.excepthook is taken


def test_the_filter_resolves_by_its_short_name_in_a_logging_configuration(tmp_path):
    """A dictConfig names the filter as `downlink.DeckLevelFilter`, the board as an argument."""
    board = tmp_path / "events" / "deck-loglevel-probe.json"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"deck_level": {"()": "downlink.DeckLevelFilter", "board_path": board}},
            "handlers": {"probe": {"class": "logging.NullHandler", "filters": ["deck_level"]}},
            "loggers": {"downlink-dictconfig": {"handlers": ["probe"]}},
        }
    )

    gate = logging.getLogger("downlink-dictconfig").handlers[0].filters[0]

    assert isinstance(gate, downlink.DeckLevelFilter)
    assert gate.board_path == board


WRITER = (
    "import sys;from pathlib import Path;from downlink import files;"
    "files.MAX_BYTES=20000;"
    "lg=files.configure(name='rotation-race', log_file=Path(sys.argv[1]));"
    "[lg.info('%s %06d %s', sys.argv[2], n, 'x'*60) for n in range(int(sys.argv[3]))]"
)


def test_two_processes_rotating_one_file_lose_no_line(tmp_path):
    """A second writer must not cost the first its lines.

    The standard library's rollover removes and renames a cascade of backups; a second process
    in the same file makes the loser raise and the record is dropped — measured 2026-08-04 at
    roughly 85 percent of 800 lines. The limit is sized so the whole run fits inside the kept
    files: what rotation discards on purpose is not what this test is about.
    """
    log_file = tmp_path / "deck.log"
    lines = 300
    writers = [
        subprocess.Popen(  # noqa: S603 — the interpreter running this suite, with a fixed script
            [sys.executable, "-c", WRITER, str(log_file), tag, str(lines)],
            stderr=subprocess.PIPE,
            text=True,
        )
        for tag in ("AAA", "BBB")
    ]
    complaints = "".join(writer.communicate()[1] for writer in writers)

    survived = {"AAA": 0, "BBB": 0}
    for rotated in tmp_path.glob("deck.log*"):
        for line in rotated.read_text(encoding="utf-8", errors="replace").splitlines():
            for tag in survived:
                if f" {tag} " in line:
                    survived[tag] += 1

    assert "--- Logging error ---" not in complaints, complaints[:800]
    assert survived == {"AAA": lines, "BBB": lines}


def test_a_directory_can_be_removed_once_its_handlers_are_released(tmp_path):
    """A handler must not outlive its directory — Windows cannot unlink an open file."""
    deck = tmp_path / "deck"
    deck.mkdir()
    downlink.configure(name="downlink-release", log_file=deck / "logs" / "probe.log").info("worth keeping")

    _release(tmp_path)
    shutil.rmtree(deck)

    assert not deck.exists()
