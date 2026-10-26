import io
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.utils import timezone

from django_notification_rules.models import (
    Delivery,
    Event,
    InboxMessage,
    NotificationRule,
    RuleChannel,
    RuleRecipient,
    RuleTemplate,
)

pytestmark = pytest.mark.django_db


def test_a_rule_needs_a_declared_event_and_a_valid_condition():
    with pytest.raises(ValidationError) as raised:
        NotificationRule(name="x", event_code="nope").full_clean()
    assert "event_code" in raised.value.message_dict

    with pytest.raises(ValidationError) as raised:
        NotificationRule(name="x", event_code="orders.placed", condition={"field": "nope", "op": "eq"}).full_clean()
    assert "condition" in raised.value.message_dict

    NotificationRule(name="x", event_code="orders.placed").full_clean()


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"kind": "user"}, "user"),
        ({"kind": "group"}, "group"),
        ({"kind": "permission", "value": "nodot"}, "value"),
        ({"kind": "resolver", "value": "nope"}, "value"),
    ],
)
def test_a_recipient_names_what_its_kind_needs(make_rule, fields, error):
    with pytest.raises(ValidationError) as raised:
        RuleRecipient(rule=make_rule(), **fields).clean()
    assert error in raised.value.message_dict


def test_a_valid_recipient_and_its_description(make_rule, member):
    rule = make_rule()
    staff = Group.objects.create(name="STAFF")
    for recipient in (
        RuleRecipient(rule=rule, kind="group", group=staff),
        RuleRecipient(rule=rule, kind="user", user=member("ann")),
        RuleRecipient(rule=rule, kind="permission", value="a.b"),
        RuleRecipient(rule=rule, kind="resolver", value="customer"),
    ):
        recipient.clean()
    assert str(RuleRecipient(rule=rule, kind="group", group=staff)) == "group STAFF"


def test_a_template_must_compile(make_rule):
    with pytest.raises(ValidationError) as raised:
        RuleTemplate(rule=make_rule(), subject="{% if %}", body="{{ ok }}", link="{% debug %}").clean()
    assert set(raised.value.message_dict) == {"subject", "link"}


def test_the_names_shown(make_rule, member):
    rule = make_rule("Big")
    event = Event.objects.create(code="orders.placed", payload={})
    ann = member("ann")
    delivery = Delivery.objects.create(event=event, channel="memory", recipient=ann)

    assert str(rule) == "Big"
    assert str(RuleChannel.objects.get()) == "memory"
    assert str(RuleTemplate(rule=rule, channel="inbox", language="")) == "inbox *"
    assert str(event) == f"orders.placed #{event.pk}"
    assert str(delivery) == "orders.placed → ann (memory, pending)"
    message = InboxMessage(user=ann, event_code="x", body="b" * 60)
    assert str(message) == "b" * 50 and not message.read


def test_the_purge_command(member):
    ann = member("ann")
    old, new = (Event.objects.create(code="orders.placed", payload={}) for _ in range(2))
    InboxMessage.objects.create(user=ann, event_code="x")
    InboxMessage.objects.create(user=ann, event_code="y")
    long_ago = timezone.now() - timedelta(days=100)
    Event.objects.filter(pk=old.pk).update(created_at=long_ago)
    InboxMessage.objects.filter(event_code="x").update(created_at=long_ago)
    out = io.StringIO()

    call_command("notification_rules_purge", "--days", "90", stdout=out)

    assert list(Event.objects.values_list("pk", flat=True)) == [new.pk]
    assert list(InboxMessage.objects.values_list("event_code", flat=True)) == ["y"]
    assert "Deleted 1 events and 1 inbox messages" in out.getvalue()
    with pytest.raises(CommandError):
        call_command("notification_rules_purge", "--days", "0")
