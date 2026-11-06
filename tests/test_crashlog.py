"""Uncaught exceptions land in a log — the process's and its threads', Ctrl+C aside."""

import logging
import sqlite3
import sys
import threading

import pytest

from downlink import crashlog


@pytest.fixture
def hooks(monkeypatch):
    """The process's exception hooks, replaced by recorders and restored afterwards.

    Returns what reached the hooks that stood before `record_crashes` took them.
    """
    passed_on = {"process": [], "thread": []}
    monkeypatch.setattr(sys, "excepthook", lambda *crash: passed_on["process"].append(crash))
    monkeypatch.setattr(threading, "excepthook", passed_on["thread"].append)
    return passed_on


@pytest.fixture
def logger(caplog):
    """A logger that caplog hears, at every level."""
    caplog.set_level(logging.DEBUG, logger="test-crashlog")
    return logging.getLogger("test-crashlog")


def test_a_process_crash_is_written_as_critical_with_its_traceback(hooks, logger, caplog):
    """Without the hook a dead worker leaves its reason on one terminal and in no log."""
    crashlog.record_crashes(logger)
    error = sqlite3.OperationalError("database is locked")

    sys.excepthook(type(error), error, None)

    [record] = caplog.records
    assert record.levelname == "CRITICAL"
    assert "sqlite3.OperationalError: database is locked" in caplog.text
    assert hooks["process"] == [(type(error), error, None)]


def test_ctrl_c_is_no_crash(hooks, logger, caplog):
    crashlog.record_crashes(logger)
    stop = KeyboardInterrupt()

    sys.excepthook(KeyboardInterrupt, stop, None)

    assert caplog.records == []
    assert hooks["process"] == [(KeyboardInterrupt, stop, None)]


def test_a_thread_crash_is_written_with_the_thread_name(hooks, logger, caplog):
    crashlog.record_crashes(logger)

    def pulse():
        raise RuntimeError("pulse lost")

    thread = threading.Thread(target=pulse, name="running-beat")
    thread.start()
    thread.join()

    [record] = caplog.records
    assert record.levelname == "CRITICAL"
    assert "running-beat" in record.getMessage()
    assert "RuntimeError: pulse lost" in caplog.text
    assert len(hooks["thread"]) == 1
