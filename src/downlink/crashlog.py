"""Write uncaught exceptions to a log; :mod:`downlink.logformat` reads them back.

Without these hooks a crash reaches only the console, and nothing that follows the log files
ever sees it. Every process that owns a log installs them once, early.
"""

import logging
import sys
import threading
import types


def record_crashes(logger: logging.Logger) -> None:
    """Log every uncaught exception to *logger* as CRITICAL, then call the previous hook.

    The previous hook still prints, so the console keeps its traceback. Ctrl+C is a stop,
    not a crash.
    """
    console = sys.excepthook
    thread_console = threading.excepthook

    def hook(kind: type[BaseException], error: BaseException, trace: types.TracebackType | None) -> None:
        if not issubclass(kind, KeyboardInterrupt):
            logger.critical("crashed: %s", kind.__name__, exc_info=(kind, error, trace))
        console(kind, error, trace)

    def thread_hook(crash: threading.ExceptHookArgs) -> None:
        if crash.exc_type is not SystemExit:
            name = crash.thread.name if crash.thread else "?"
            logger.critical(
                "thread %s crashed: %s",
                name,
                crash.exc_type.__name__,
                # exc_value may be None here; logging formats that as well.
                exc_info=(crash.exc_type, crash.exc_value, crash.exc_traceback),  # ty: ignore[invalid-argument-type]
            )
        thread_console(crash)

    sys.excepthook = hook
    threading.excepthook = thread_hook
