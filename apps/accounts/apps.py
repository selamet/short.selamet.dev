from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        from django.tasks.signals import task_finished

        from .signals import log_failed_task

        task_finished.connect(log_failed_task, dispatch_uid="accounts.log_failed_task")
