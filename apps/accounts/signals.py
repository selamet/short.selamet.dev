"""Task lifecycle signal handlers for the accounts app."""

import logging

from django.tasks import TaskResultStatus

logger = logging.getLogger("apps.accounts.tasks")


def log_failed_task(sender, task_result, **kwargs):
    """Log an ERROR when a task finishes with a failed status.

    django.tasks already logs every finished task at INFO/ERROR under the
    "django.tasks" logger; this adds a dedicated, easy-to-alert-on record under the
    accounts task logger with the failing task's module path and last traceback.
    """
    if task_result.status != TaskResultStatus.FAILED:
        return
    last_error = task_result.errors[-1] if task_result.errors else None
    logger.error(
        "Task failed path=%s\n%s",
        task_result.task.module_path,
        last_error.traceback if last_error else "",
    )
