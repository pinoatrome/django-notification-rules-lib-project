import pytest
from django.contrib.auth.models import Group

from django_notification_rules import events, recipients
from django_notification_rules.channels import memory
from django_notification_rules.models import NotificationRule, RuleChannel, RuleRecipient, RuleTemplate


@pytest.fixture(autouse=True)
def registries():
    """The event types and resolvers a test declares don't outlive it."""
    saved_events, saved_resolvers = dict(events.REGISTRY), dict(recipients.REGISTRY)
    yield
    events.REGISTRY.clear()
    events.REGISTRY.update(saved_events)
    recipients.REGISTRY.clear()
    recipients.REGISTRY.update(saved_resolvers)


@pytest.fixture(autouse=True)
def outbox():
    memory.outbox.clear()
    yield memory.outbox
    memory.outbox.clear()


@pytest.fixture
def member(db, django_user_model):
    """A user in the given groups (created if missing)."""

    def make(username="ann", *groups, **fields):
        user = django_user_model.objects.create_user(username=username, **fields)
        user.groups.add(*(Group.objects.get_or_create(name=name)[0] for name in groups))
        return user

    return make


@pytest.fixture
def make_rule(db):
    """A rule of `event` sending through `channels` to `recipients` ((kind, user|group|value) pairs), with
    `templates` ({(channel, language): (subject, body, link)})."""

    def make(
        name="rule",
        event="orders.placed",
        *,
        channels=("memory",),
        recipients=(),
        templates=None,
        condition=None,
        enabled=True,
    ):
        rule = NotificationRule.objects.create(name=name, event_code=event, condition=condition or {}, enabled=enabled)
        for code in channels:
            RuleChannel.objects.create(rule=rule, channel=code)
        for kind, target in recipients:
            fields = {"user": {"user": target}, "group": {"group": target}}.get(kind, {"value": target})
            RuleRecipient.objects.create(rule=rule, kind=kind, **fields)
        for (channel, language), (subject, body, link) in (templates or {}).items():
            RuleTemplate.objects.create(
                rule=rule, channel=channel, language=language, subject=subject, body=body, link=link
            )
        return rule

    return make


@pytest.fixture
def emit(django_capture_on_commit_callbacks):
    """`events.emit`, its on-commit work run at once (the test's transaction never commits)."""

    def run(code, **payload):
        with django_capture_on_commit_callbacks(execute=True):
            events.emit(code, **payload)

    return run
