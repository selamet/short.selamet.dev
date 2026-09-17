from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    name = "apps.workspaces"
    label = "workspaces"

    def ready(self):
        from django.conf import settings
        from django.db.models.signals import pre_delete

        from .signals import reassign_ownership_on_user_delete

        pre_delete.connect(
            reassign_ownership_on_user_delete,
            sender=settings.AUTH_USER_MODEL,
            dispatch_uid="workspaces.reassign_ownership_on_user_delete",
        )
