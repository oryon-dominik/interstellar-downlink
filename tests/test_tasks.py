"""Task lines say what the worker works on now — each line names its task, a run reads as one block."""

import datetime
import logging
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.tasks import task
from django.test import override_settings
from django.utils import timezone
from django_scheduled_tasks import periodic_task
from django_scheduled_tasks.base import scheduler
from django_scheduled_tasks.models import ScheduledTaskRunLog

from downlink import stamps, tasks

inside = logging.getLogger("shop.commands")


@periodic_task(interval=datetime.timedelta(minutes=15))
@task
def send_invoices() -> None:
    """A task that goes well and says what it did."""
    inside.info("sent 0")


@task(queue_name="payments")
def sync_refunds() -> None:
    """A task that breaks."""
    raise ValueError("no provider")


@task
def charge_order(order_id: str, *, attempt: int = 1) -> None:
    """A task that works on one thing."""


@pytest.fixture
def scheduler_queues(monkeypatch: pytest.MonkeyPatch):
    """Let this process queue as the scheduler does."""
    monkeypatch.setattr(apps.get_app_config("downlink_tasks"), "queuing_part", "scheduler")


@pytest.fixture
def overdue_run_log(scheduler_queues):
    """Give send_invoices a run log whose due time lies ten minutes back."""
    call_command("migrate", "django_scheduled_tasks", verbosity=0)
    (schedule,) = (each for each in scheduler.schedules if each.task.module_path == send_invoices.module_path)
    due = timezone.now() - datetime.timedelta(minutes=10)
    run_log = ScheduledTaskRunLog.objects.create(task_hash=schedule.to_sha_hex(), next_scheduled_run_time=due)
    yield run_log
    run_log.delete()


def lines(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str, str]]:
    return [(record.name, record.levelname, record.getMessage()) for record in caplog.records]


def test_a_line_reads_job_mark_outcome_and_what_is_known():
    assert tasks.line(job="send_invoices", outcome="running", parts=["default", "", "waited 4s"]) == (
        "send_invoices ▶ running default · waited 4s"
    )


def test_a_line_folds_away_what_it_does_not_know():
    assert tasks.line(job="send_invoices", outcome="ok", parts=[]) == "send_invoices ✓ ok"


def test_arguments_read_like_a_call():
    assert tasks.arguments(["0193f2a4", 2], {"attempt": 2}) == "0193f2a4, 2, attempt=2"


def test_a_long_argument_is_cut_short():
    assert tasks.arguments(["x" * 60], {}) == "x" * 39 + "…"


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [(45.9, "45s"), (60, "1m"), (252, "4m12s"), (3600, "1h"), (3900, "1h05m")],
)
def test_a_duration_reads_at_a_glance(seconds: float, shown: str):
    assert tasks.duration(seconds) == shown


def test_a_run_tells_how_long_it_waited_once_that_is_a_second():
    queued = datetime.datetime(2026, 11, 4, 8, 3, 45, tzinfo=datetime.UTC)
    waiting = SimpleNamespace(enqueued_at=queued, started_at=queued + datetime.timedelta(seconds=4))
    eager = SimpleNamespace(enqueued_at=queued, started_at=queued + datetime.timedelta(milliseconds=300))

    assert tasks.waited(waiting) == "waited 4s"
    assert tasks.waited(eager) == ""


@pytest.mark.parametrize(
    ("argv", "part"),
    [
        (["manage.py", "run_task_scheduler", "--no-reload"], "scheduler"),
        (["manage.py", "db_worker"], "tasks"),
        (["manage.py", "runserver"], "tasks"),
    ],
)
def test_only_the_scheduler_queues_as_the_scheduler(argv: list[str], part: str):
    assert tasks.part(argv) == part


def test_a_run_reads_as_one_block_on_the_project_and_queue(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        send_invoices.enqueue()

    assert lines(caplog) == [
        ("shop.tasks.default", "INFO", "send_invoices ○ queued default"),
        ("shop.worker.default", "INFO", "send_invoices ▶ running default"),
        ("shop.commands", "INFO", "sent 0"),
        ("shop.worker.default", "INFO", "send_invoices ✓ ok 0s"),
    ]


def test_what_a_task_writes_while_it_runs_carries_its_name(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        send_invoices.enqueue()

    assert [getattr(record, "running_task", None) for record in caplog.records] == [
        None,
        None,
        "send_invoices",
        None,
    ]


def test_a_run_shows_what_it_works_on(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        charge_order.enqueue("0193f2a4", attempt=2)

    assert lines(caplog)[:2] == [
        ("shop.tasks.default", "INFO", "charge_order ○ queued default · 0193f2a4, attempt=2"),
        ("shop.worker.default", "INFO", "charge_order ▶ running default · 0193f2a4, attempt=2"),
    ]


def test_a_failed_run_is_an_error_with_its_traceback(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        sync_refunds.enqueue()

    failed = caplog.records[-1]
    assert failed.name == "shop.worker.payments"
    assert failed.levelname == "ERROR"
    assert failed.getMessage() == "sync_refunds ✗ fail 0s · ValueError: no provider"
    assert failed.exc_info is not None


def test_django_writes_no_task_lines_of_its_own(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.DEBUG):
        send_invoices.enqueue()
        sync_refunds.enqueue()

    assert not [record for record in caplog.records if record.name.startswith("django.tasks")]


def test_the_scheduler_queues_with_its_schedule_lateness_and_next_run(
    overdue_run_log: ScheduledTaskRunLog, caplog: pytest.LogCaptureFixture
):
    following = stamps.clock(
        overdue_run_log.next_scheduled_run_time + datetime.timedelta(minutes=15),
        zone=timezone.get_default_timezone,
    )

    with caplog.at_level(logging.INFO):
        send_invoices.enqueue()

    assert lines(caplog)[0] == (
        "shop.scheduler.default",
        "INFO",
        f"send_invoices ○ queued default · late 10m · every 15 minutes · next {following}",
    )


def test_an_unscheduled_task_queues_plainly_even_from_the_scheduler(
    scheduler_queues, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.INFO):
        sync_refunds.enqueue()

    assert lines(caplog)[0] == ("shop.scheduler.payments", "INFO", "sync_refunds ○ queued payments")


def test_the_scheduler_s_own_enqueuing_line_gives_way_to_the_task_line(caplog: pytest.LogCaptureFixture):
    library = logging.getLogger("django_scheduled_tasks.base")

    with caplog.at_level(logging.INFO):
        library.info("Enqueuing task Task(func=<function send_invoices at 0x0>), is/was due 2026-11-04.")
        library.warning("Database error while processing task")

    assert lines(caplog) == [("django_scheduled_tasks.base", "WARNING", "Database error while processing task")]


@override_settings(DOWNLINK_TASK_LOGGER_PREFIX="")
def test_a_project_must_name_itself():
    with pytest.raises(ImproperlyConfigured, match="DOWNLINK_TASK_LOGGER_PREFIX"):
        apps.get_app_config("downlink_tasks").ready()
