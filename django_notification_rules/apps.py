from django.apps import AppConfig


class NotificationRulesConfig(AppConfig):
    name = "django_notification_rules"
    label = "django_notification_rules"
    verbose_name = "Notification rules"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import checks, events, recipients, signals  # noqa: F401  (registers the checks and the receivers)

        events.discover()
        recipients.discover()
