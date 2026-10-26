"""The rules as a document (a dict, written as YAML), to keep them with a project's code or move them between
deployments:

    rules:
      - name: Big orders to the sales team
        event: orders.placed
        enabled: true
        condition: {field: amount, op: gte, value: "1000"}
        recipients:
          - group: SALES
          - permission: shop.view_order
          - resolver: customer
          - user: ann
        channels: [inbox, email]          # or {email: {enabled: false}} to keep one off
        templates:
          - {channel: "*", language: "", subject: "Order {{ number }}", body: "...", link: "/orders/{{ number }}"}

`export_rules()` writes the stored rules; `load_rules(document, keep=False)` stores them in one transaction: a rule
is matched by its name (its recipients, channels and templates replaced), a group named is created when missing, a
user must exist, and without `keep` the rules the document doesn't name are deleted. YAML needs PyYAML (the `yaml`
extra).
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction

from .models import NotificationRule, RuleChannel, RuleRecipient, RuleTemplate


class RulesDocumentError(ValueError):
    """A document that can't be loaded: every problem in `errors`; nothing was stored."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _recipient(recipient: RuleRecipient) -> dict:
    if recipient.kind == "user":
        return {"user": recipient.user.get_username() if recipient.user else None}
    if recipient.kind == "group":
        return {"group": recipient.group.name if recipient.group else None}
    return {recipient.kind: recipient.value}


def export_rules(queryset=None) -> dict:
    rules = (
        (queryset if queryset is not None else NotificationRule.objects.all())
        .prefetch_related("recipients__user", "recipients__group", "channels", "templates")
        .order_by("event_code", "name")
    )
    exported = []
    for rule in rules:
        channels = list(rule.channels.all())
        entry = {"name": rule.name, "event": rule.event_code}
        if rule.description:
            entry["description"] = rule.description
        entry["enabled"] = rule.enabled
        if rule.condition:
            entry["condition"] = rule.condition
        entry["recipients"] = [_recipient(r) for r in rule.recipients.all()]
        entry["channels"] = (
            [c.channel for c in channels]
            if all(c.enabled for c in channels)
            else {c.channel: {"enabled": c.enabled} for c in channels}
        )
        templates = [
            {"channel": t.channel, "language": t.language, "subject": t.subject, "body": t.body, "link": t.link}
            for t in rule.templates.all().order_by("channel", "language")
        ]
        if templates:
            entry["templates"] = templates
        exported.append(entry)
    return {"rules": exported}


def _channels(value) -> list[tuple[str, bool]]:
    if isinstance(value, dict):
        return [(code, bool((options or {}).get("enabled", True))) for code, options in value.items()]
    return [(code, True) for code in value or []]


def _store(entry: dict, errors: list[str]) -> str | None:
    where = f"rule {entry.get('name')!r}"
    if not entry.get("name") or not entry.get("event"):
        errors.append(f"{where}: a rule needs a name and an event")
        return None
    rule = NotificationRule.objects.filter(name=entry["name"]).first() or NotificationRule(name=entry["name"])
    rule.event_code = entry["event"]
    rule.description = entry.get("description", "")
    rule.enabled = bool(entry.get("enabled", True))
    rule.condition = entry.get("condition") or {}
    try:
        rule.full_clean(validate_unique=False)
    except ValidationError as exc:
        errors += [
            f"{where}: {field}: {message}" for field, messages in exc.message_dict.items() for message in messages
        ]
        return None
    rule.save()
    rule.recipients.all().delete()
    rule.channels.all().delete()
    rule.templates.all().delete()
    User = get_user_model()
    for item in entry.get("recipients") or []:
        if not isinstance(item, dict) or len(item) != 1:
            errors.append(f"{where}: a recipient is one of user, group, permission, resolver: {item!r}")
            continue
        kind, value = next(iter(item.items()))
        recipient = RuleRecipient(rule=rule, kind=kind)
        if kind == "user":
            recipient.user = User.objects.filter(**{User.USERNAME_FIELD: value}).first()
            if recipient.user is None:
                errors.append(f"{where}: no user {value!r}")
                continue
        elif kind == "group":
            recipient.group = Group.objects.get_or_create(name=value)[0]
        else:
            recipient.value = str(value)
        try:
            recipient.full_clean()
        except ValidationError as exc:
            errors += [f"{where}: {kind} {value!r}: {message}" for message in exc.messages]
            continue
        recipient.save()
    for code, enabled in _channels(entry.get("channels")):
        RuleChannel.objects.create(rule=rule, channel=code, enabled=enabled)
    for item in entry.get("templates") or []:
        template = RuleTemplate(
            rule=rule,
            channel=item.get("channel", "*"),
            language=item.get("language", ""),
            subject=item.get("subject", ""),
            body=item.get("body", ""),
            link=item.get("link", ""),
        )
        try:
            template.full_clean()
        except ValidationError as exc:
            errors += [f"{where}: template {template}: {message}" for message in exc.messages]
            continue
        template.save()
    return rule.name


def load_rules(document: dict, keep: bool = False) -> dict:
    """Store the document's rules (see the module). Returns {"stored": [names], "deleted": [names]}; raises
    `RulesDocumentError`, having stored nothing."""
    if not isinstance(document, dict) or not isinstance(document.get("rules", []), list):
        raise RulesDocumentError(["The document is a mapping with a list of rules under 'rules'"])
    errors: list[str] = []
    with transaction.atomic():
        stored = [name for entry in document.get("rules") or [] if (name := _store(entry, errors))]
        deleted = []
        if not keep:
            gone = NotificationRule.objects.exclude(name__in=stored)
            deleted = sorted(gone.values_list("name", flat=True))
            gone.delete()
        if errors:
            transaction.set_rollback(True)
            raise RulesDocumentError(errors)
    return {"stored": stored, "deleted": deleted}


def _yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - the tests run with PyYAML
        raise ImproperlyConfigured(
            "Reading and writing YAML needs PyYAML: pip install django-notification-rules[yaml]"
        ) from exc
    return yaml


def dump_yaml(document: dict) -> str:
    return _yaml().safe_dump(document, sort_keys=False, allow_unicode=True)


def parse_yaml(text: str) -> dict:
    yaml = _yaml()
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise RulesDocumentError([f"Not YAML: {exc}"]) from exc
