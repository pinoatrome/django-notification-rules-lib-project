"""The system checks: the settings (`django_notification_rules.E001`... on every `check`), and the stored rules
against the code and the settings (`W101`..., with `check --database default`: they read the database).

| id | what |
|---|---|
| E001 | a channel of `CHANNELS` without a BACKEND, or whose BACKEND can't be imported |
| E002 | `RUNNER`, `USER_LANGUAGE` that can't be imported |
| W001 | `CACHE` isn't an alias of `CACHES` |
| W002 | `CACHE` is a LocMemCache: each process would keep its own rules |
| W101 | a rule of an event type the code doesn't declare |
| W102 | a rule whose channel isn't set up |
| W103 | a recipient naming a resolver the code doesn't declare, or a permission that doesn't exist |
| E101 | a rule whose condition can't be evaluated, or a template that doesn't compile |

The stored rules aren't checked on a database the library's migrations haven't reached (`migrate` runs the database
checks before it migrates): the migrations' own checks tell.
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.db import DatabaseError
from django.utils.module_loading import import_string

from . import conf

ID = "django_notification_rules"


@register()
def check_settings(app_configs=None, **kwargs):
    messages = []
    for code, options in (conf.get("CHANNELS") or {}).items():
        path = (options or {}).get("BACKEND")
        if not path:
            messages.append(Error(f"Channel {code!r} has no BACKEND.", id=f"{ID}.E001"))
            continue
        try:
            import_string(path)
        except ImportError as exc:
            messages.append(Error(f"Channel {code!r}: can't import {path!r}: {exc}", id=f"{ID}.E001"))
    for name in ("RUNNER", "USER_LANGUAGE"):
        path = conf.get(name)
        if path:
            try:
                import_string(path)
            except ImportError as exc:
                messages.append(Error(f"NOTIFICATION_RULES[{name!r}]: can't import {path!r}: {exc}", id=f"{ID}.E002"))
    alias = conf.get("CACHE")
    if alias is not None:
        backend = settings.CACHES.get(alias, {}).get("BACKEND", "") if alias in settings.CACHES else None
        if backend is None:
            messages.append(
                Warning(
                    f"NOTIFICATION_RULES['CACHE'] {alias!r} isn't an alias of CACHES.",
                    id=f"{ID}.W001",
                    hint="Name one of CACHES, or None to read the rules from the database.",
                )
            )
        elif backend.endswith("LocMemCache"):
            messages.append(
                Warning(
                    f"NOTIFICATION_RULES['CACHE'] {alias!r} is a LocMemCache: each process keeps its own copy of the "
                    "rules, and a rule changed in one isn't seen by the others until it expires.",
                    id=f"{ID}.W002",
                    hint="Use a cache every process shares (Redis, Memcached, the database cache), or None.",
                )
            )
    return messages


@register(Tags.database)
def check_rules(app_configs=None, databases=None, **kwargs):
    if not databases:
        return []
    try:
        return _stored_rules()
    except DatabaseError:  # not migrated yet: the migrations' own checks tell
        return []


def _stored_rules():
    from django.contrib.auth.models import Permission

    from . import channels, conditions, events, recipients, templating
    from .models import NotificationRule, RuleChannel, RuleRecipient, RuleTemplate

    messages = []
    known_channels = set(channels.codes())
    for rule in NotificationRule.objects.all():
        try:
            event_type = events.get(rule.event_code)
        except events.UnknownEvent:
            messages.append(
                Warning(
                    f"Rule {rule.name!r}: no event type {rule.event_code!r} is declared.", id=f"{ID}.W101", obj=rule
                )
            )
            continue
        try:
            conditions.validate(rule.condition, event_type)
        except conditions.ConditionError as exc:
            messages.append(Error(f"Rule {rule.name!r}: its condition: {exc}", id=f"{ID}.E101", obj=rule))
    for channel in RuleChannel.objects.select_related("rule").exclude(channel__in=known_channels):
        messages.append(
            Warning(
                f"Rule {channel.rule.name!r}: channel {channel.channel!r} isn't set up.",
                id=f"{ID}.W102",
                obj=channel.rule,
            )
        )
    for recipient in RuleRecipient.objects.select_related("rule").filter(kind__in=("resolver", "permission")):
        if recipient.kind == "resolver" and recipient.value not in recipients.REGISTRY:
            messages.append(
                Warning(
                    f"Rule {recipient.rule.name!r}: no resolver {recipient.value!r} is declared.",
                    id=f"{ID}.W103",
                    obj=recipient.rule,
                )
            )
        if recipient.kind == "permission":
            label, _, codename = recipient.value.partition(".")
            if not Permission.objects.filter(content_type__app_label=label, codename=codename).exists():
                messages.append(
                    Warning(
                        f"Rule {recipient.rule.name!r}: no permission {recipient.value!r}.",
                        id=f"{ID}.W103",
                        obj=recipient.rule,
                    )
                )
    for template in RuleTemplate.objects.select_related("rule"):
        for name in ("subject", "body", "link"):
            try:
                templating.check(getattr(template, name))
            except templating.TemplateError as exc:
                messages.append(
                    Error(
                        f"Rule {template.rule.name!r}: template {template} {name}: {exc}",
                        id=f"{ID}.E101",
                        obj=template.rule,
                    )
                )
    return messages
