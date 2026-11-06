"""Task lines for a Django project: what the worker runs now, and what was queued.

Django writes its task lines under ``django.tasks`` as ``Task id=… path=… state=…``, and side by
side they name neither the project nor the queue. This app takes over from Django's three log
receivers. A run reads as one block, every line led by its task::

    send_invoices ○ queued default · every 15 minutes · next 08:18:45
    send_invoices ▶ running default
    send_invoices │ invoices sent 12, failed 0
    send_invoices ✓ ok 0s
    charge_order ▶ running payments · 0193f2a4, attempt=2 · waited 4s
    sync_refunds ✗ fail 2s · ValueError: no provider

Whatever a task logs while it runs carries the task's name as ``running_task`` on its record;
:class:`downlink.ConsoleHandler` sets such a line under the name, the ``│`` line above. Where
django-scheduled-tasks is installed, the scheduler's line adds the schedule, how late the run
was and when it comes next, in place of that library's own ``Enqueuing task Task(func=…)`` line.

A logger name is the prefix, the part the process plays and the queue: ``shop.worker.default``
for a run, ``shop.scheduler.default`` for what the scheduler queued, ``shop.tasks.default``
for what any other process queued.

A project installs it with two settings::

    INSTALLED_APPS = [..., "downlink.tasks.TaskLines"]
    DOWNLINK_TASK_LOGGER_PREFIX = "shop"
"""

import datetime
import logging
import sys
from collections.abc import Iterable
from contextvars import ContextVar

from django.apps import AppConfig, apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.tasks import signals
from django.tasks.base import TaskResult, TaskResultStatus
from django.utils import timezone

from downlink import stamps

#: The scheduler's management command: what it queues, it queues as the scheduler.
SCHEDULER_COMMAND = "run_task_scheduler"
#: The logger django-scheduled-tasks writes its ``Enqueuing task`` line on.
SCHEDULER_LOGGER = "django_scheduled_tasks.base"
MARKS = {"queued": "○", "running": "▶", "ok": "✓", "fail": "✗"}
#: A line shows what a run works on, not its payload, so a longer argument is cut.
ARGUMENT_WIDTH = 40
#: The scheduler looks every second; a run shows as late once it slipped further than this.
LATE = datetime.timedelta(minutes=1)

#: The task this thread runs right now.
running: ContextVar[str | None] = ContextVar("running_task", default=None)


def part(argv: list[str]) -> str:
    """Name the part this process plays when it queues a task: the scheduler, or any other."""
    return "scheduler" if SCHEDULER_COMMAND in argv else "tasks"


def duration(seconds: float) -> str:
    """Format a duration for a glance: ``45s``, ``4m12s``, ``1h05m``."""
    minutes, rest = divmod(int(seconds), 60)
    if not minutes:
        return f"{rest}s"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes}m{rest:02d}s" if rest else f"{minutes}m"
    return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"


def line(*, job: str, outcome: str, parts: Iterable[str]) -> str:
    """Build a line: job, mark, outcome, then what is known; what is not known folds away."""
    known = " · ".join(each for each in parts if each)
    return f"{job} {MARKS[outcome]} {outcome} {known}".rstrip()


def _short(value: object) -> str:
    text = str(value)
    return text if len(text) <= ARGUMENT_WIDTH else f"{text[: ARGUMENT_WIDTH - 1]}…"


def arguments(args: list, kwargs: dict) -> str:
    """Render a run's arguments as a call reads them: ``0193f2a4, attempt=2``."""
    return ", ".join([*map(_short, args), *(f"{name}={_short(value)}" for name, value in kwargs.items())])


def waited(task_result: TaskResult) -> str:
    """Say how long the run sat in the queue; nothing under a second."""
    if task_result.enqueued_at is None or task_result.started_at is None:
        return ""
    seconds = (task_result.started_at - task_result.enqueued_at).total_seconds()
    return f"waited {duration(seconds)}" if seconds >= 1 else ""


def _took(task_result: TaskResult) -> str:
    if task_result.started_at is None or task_result.finished_at is None:
        return ""
    return duration((task_result.finished_at - task_result.started_at).total_seconds())


def schedule_parts(task_result: TaskResult) -> list[str]:
    """Say how late the scheduler queued the run, its schedule and when it comes next."""
    from django_scheduled_tasks.base import scheduler
    from django_scheduled_tasks.models import ScheduledTaskRunLog

    schedule = next(
        (
            each
            for each in scheduler.schedules
            if each.task.module_path == task_result.task.module_path
            and list(each.task_args) == list(task_result.args)
            and each.task_kwargs == task_result.kwargs
        ),
        None,
    )
    if schedule is None:
        return []
    now = task_result.enqueued_at or timezone.now()
    try:
        # The scheduler advances the due time only after the task is queued, so it is still this run's.
        due = (
            ScheduledTaskRunLog.objects.filter(  # ty: ignore[unresolved-attribute]  # Django adds the manager
                task_hash=schedule.to_sha_hex()
            )
            .values_list("next_scheduled_run_time", flat=True)
            .first()
        )
    except DatabaseError:
        # The task is already queued: raising here would keep the scheduler from noting it and queue it twice.
        due = None
    following = schedule.get_next_scheduled_time(due or now, now)
    return [
        f"late {duration((now - due).total_seconds())}" if due and now - due >= LATE else "",
        schedule.get_schedule_description(),
        f"next {stamps.clock(following, zone=timezone.get_default_timezone)}",
    ]


def without_enqueuing_lines(record: logging.LogRecord) -> bool:
    """Drop the scheduler library's ``Enqueuing task`` line; the queued task line says it all."""
    return not str(record.msg).startswith("Enqueuing task ")


class RunningTaskRecords:
    """A log record factory that notes, on every record, the task its thread runs."""

    def __init__(self, factory) -> None:
        self.factory = factory

    def __call__(self, *args, **kwargs) -> logging.LogRecord:
        record = self.factory(*args, **kwargs)
        record.running_task = running.get()
        return record


class TaskLines(AppConfig):
    """Write the project's task lines in place of Django's own."""

    name = "downlink.tasks"
    label = "downlink_tasks"

    def ready(self) -> None:
        self.logger_prefix = getattr(settings, "DOWNLINK_TASK_LOGGER_PREFIX", "")
        if not self.logger_prefix:
            raise ImproperlyConfigured(
                "downlink.tasks needs DOWNLINK_TASK_LOGGER_PREFIX: the start of its logger names"
            )
        self.queuing_part = part(sys.argv)
        self.scheduled = apps.is_installed("django_scheduled_tasks")
        if self.scheduled:
            logging.getLogger(SCHEDULER_LOGGER).addFilter(without_enqueuing_lines)
        if not isinstance(logging.getLogRecordFactory(), RunningTaskRecords):
            logging.setLogRecordFactory(RunningTaskRecords(logging.getLogRecordFactory()))
        for signal, django_receiver, receiver in (
            (signals.task_enqueued, signals.log_task_enqueued, self.queued),
            (signals.task_started, signals.log_task_started, self.started),
            (signals.task_finished, signals.log_task_finished, self.finished),
        ):
            signal.disconnect(django_receiver)
            signal.connect(receiver, dispatch_uid=f"downlink.tasks.{receiver.__name__}")

    def _logger(self, role: str, task_result: TaskResult) -> logging.Logger:
        return logging.getLogger(f"{self.logger_prefix}.{role}.{task_result.task.queue_name}")

    def _work(self, task_result: TaskResult) -> list[str]:
        return [task_result.task.queue_name, arguments(task_result.args, task_result.kwargs)]

    def queued(self, sender, task_result: TaskResult, **kwargs) -> None:
        parts = self._work(task_result)
        if self.scheduled and self.queuing_part == "scheduler":
            parts += schedule_parts(task_result)
        self._logger(self.queuing_part, task_result).info(
            line(job=task_result.task.name, outcome="queued", parts=parts)
        )

    def started(self, sender, task_result: TaskResult, **kwargs) -> None:
        # Logged before the run begins: the task's own lines appear under this one.
        self._logger("worker", task_result).info(
            line(job=task_result.task.name, outcome="running", parts=[*self._work(task_result), waited(task_result)])
        )
        running.set(task_result.task.name)

    def finished(self, sender, task_result: TaskResult, **kwargs) -> None:
        running.set(None)
        # Django sends a failure from inside its exception handler: the error is still at hand.
        error = sys.exc_info()[1]
        failed = task_result.status == TaskResultStatus.FAILED
        self._logger("worker", task_result).log(
            logging.ERROR if failed else logging.INFO,
            line(
                job=task_result.task.name,
                outcome="fail" if failed else "ok",
                parts=[_took(task_result), f"{type(error).__name__}: {error}" if failed and error else ""],
            ),
            exc_info=error if failed else None,
        )
