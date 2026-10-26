"""The channels a rule sends through, as `NOTIFICATION_RULES["CHANNELS"]` sets them up:

    NOTIFICATION_RULES = {"CHANNELS": {
        "inbox": {"BACKEND": "django_notification_rules.channels.inbox.InboxChannel"},
        "console": {"BACKEND": "django_notification_rules.channels.console.ConsoleChannel", "STREAM": "stdout"},
    }}

Each entry is a code (what the rules name) and its backend, a `BaseChannel` subclass, with its options (the other
keys). None is required: a project sets up those it has, and a rule can only use those.

Shipped: `inbox` (the in-app inbox, `InboxMessage`), `console` (writes each notification out: development), and
`memory` (keeps them in a list: tests).
"""

from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .. import conf
from .base import BaseChannel, ChannelError

__all__ = ["BaseChannel", "ChannelError", "codes", "choices", "get"]


def configured() -> dict[str, dict]:
    return dict(conf.get("CHANNELS") or {})


def codes() -> list[str]:
    return list(configured())


def get(code: str) -> BaseChannel:
    """The channel set up as `code`. Raises `ChannelError` for a code that isn't set up, `ImproperlyConfigured`
    for a backend that can't be imported."""
    options = configured().get(code)
    if options is None:
        raise ChannelError(f"No channel {code!r} is set up (NOTIFICATION_RULES['CHANNELS'])")
    options = dict(options)
    path = options.pop("BACKEND", "")
    try:
        backend = import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(f"Channel {code!r}: can't import its BACKEND {path!r}: {exc}") from exc
    return backend(code, **options)


def choices() -> list[tuple[str, str]]:
    found = []
    for code in codes():
        try:
            label = get(code).label
        except (ChannelError, ImproperlyConfigured):
            label = ""
        found.append((code, f"{code} — {label}" if label else code))
    return found
