"""`python manage.py enqueue_scheduled <name>`: enqueue exactly one of the scheduled
analytics/maintenance tasks by name. Meant to be invoked by supercronic from
docker/crontab (see that file and compose.yaml): the crontab only ever enqueues
work, the worker container (`manage.py db_worker`) is what actually executes it, so
nothing in the web process schedules anything on its own.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.tasks import (
    expire_links,
    purge_click_events,
    rebuild_daily_stats,
    rotate_ip_salt,
)

TASKS = {
    "rebuild_daily_stats": rebuild_daily_stats,
    "purge_click_events": purge_click_events,
    "rotate_ip_salt": rotate_ip_salt,
    "expire_links": expire_links,
}


class Command(BaseCommand):
    help = "Enqueue one of the scheduled analytics/maintenance tasks by name."

    def add_arguments(self, parser):
        parser.add_argument("name", help=f"One of: {', '.join(sorted(TASKS))}.")

    def handle(self, *args, **options):
        name = options["name"]
        try:
            scheduled_task = TASKS[name]
        except KeyError:
            raise CommandError(
                f"Unknown scheduled task {name!r}. Choices: {', '.join(sorted(TASKS))}."
            ) from None
        result = scheduled_task.enqueue()
        self.stdout.write(f"enqueued {name} ({result.id})")
