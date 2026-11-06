"""A Django project in miniature: the task lines installed, tasks run in the test's own process."""

import django
from django.conf import settings

settings.configure(
    INSTALLED_APPS=["django_scheduled_tasks", "downlink.tasks.TaskLines"],
    DOWNLINK_TASK_LOGGER_PREFIX="shop",
    # The scheduler's run log, where a scheduled task's due time waits.
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    TASKS={
        "default": {
            "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
            "QUEUES": ["default", "payments"],
        }
    },
    TIME_ZONE="UTC",
    USE_TZ=True,
)
django.setup()
