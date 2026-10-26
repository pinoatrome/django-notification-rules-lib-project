"""The library's settings: `NOTIFICATION_RULES` in the project's settings, a dict whose keys override `DEFAULTS`."""

from django.conf import settings
from django.utils.module_loading import import_string

DEFAULTS = {
    # The channels a rule may use, by code: {"inbox": {"BACKEND": "django_notification_rules.channels.inbox.
    # InboxChannel"}, ...}, each with its backend's options. None is required: a rule chooses among those set here.
    "CHANNELS": {
        "inbox": {"BACKEND": "django_notification_rules.channels.inbox.InboxChannel"},
    },
    # The dotted path of a function (event_id) that has the rules act on an event once it's recorded: in the same
    # process (the default), or queued for a worker.
    "RUNNER": "django_notification_rules.runners.run_now",
    # An alias of CACHES holding each event type's rules between events; None reads the database each time. The
    # cache must be shared by every process of the project (Redis, Memcached, the database cache), not a
    # LocMemCache.
    "CACHE": "default",
    "CACHE_TIMEOUT": 300,
    # The dotted path of a function (user) -> language code, the language a recipient's texts are written in;
    # None: settings.LANGUAGE_CODE for everyone.
    "USER_LANGUAGE": None,
    # The authentication backend asked for the holders of a permission (`User.objects.with_perm`), needed when the
    # project has more than one; None: Django's choice.
    "PERMISSION_BACKEND": None,
}


def get(name: str):
    return {**DEFAULTS, **getattr(settings, "NOTIFICATION_RULES", {})}[name]


def runner():
    return import_string(get("RUNNER"))


def user_language(user) -> str:
    """The language `user`'s texts are written in (`USER_LANGUAGE`, else the project's)."""
    path = get("USER_LANGUAGE")
    language = import_string(path)(user) if path else None
    return language or settings.LANGUAGE_CODE
