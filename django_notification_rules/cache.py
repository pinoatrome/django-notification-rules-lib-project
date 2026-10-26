"""Each event type's enabled rules, as the dispatcher reads them: plain data, kept in the cache `CACHE` (shared by
every process) under a key of their own, dropped when a rule changes (`signals`), once the transaction commits."""

from django.core.cache import caches

from . import conf

KEY = "django_notification_rules:rules:{code}"


def load(code: str) -> list[dict]:
    """The enabled rules of `code`, from the database: their condition, recipients, enabled channels, templates."""
    from .models import NotificationRule

    rules = (NotificationRule.objects.filter(event_code=code, enabled=True)
             .prefetch_related("recipients", "channels", "templates").order_by("name"))
    return [
        {
            "id": rule.pk,
            "name": rule.name,
            "condition": rule.condition or {},
            "recipients": [recipient.spec() for recipient in rule.recipients.all()],
            "channels": [channel.channel for channel in rule.channels.all() if channel.enabled],
            "templates": [
                {"channel": t.channel, "language": t.language, "subject": t.subject, "body": t.body, "link": t.link}
                for t in rule.templates.all()
            ],
        }
        for rule in rules
    ]


def rules_for(code: str) -> list[dict]:
    alias = conf.get("CACHE")
    if alias is None:
        return load(code)
    cache = caches[alias]
    key = KEY.format(code=code)
    found = cache.get(key)
    if found is None:
        found = load(code)
        cache.set(key, found, conf.get("CACHE_TIMEOUT"))
    return found


def forget(*codes: str) -> None:
    """Drop the cached rules of `codes` (every event type's, the code's and the database's, when none)."""
    alias = conf.get("CACHE")
    if alias is None:
        return
    if not codes:
        from . import events
        from .models import NotificationRule

        codes = tuple(set(events.REGISTRY) | set(NotificationRule.objects.values_list("event_code", flat=True)))
    caches[alias].delete_many([KEY.format(code=code) for code in codes])
