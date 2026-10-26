import pytest
from django.utils import timezone

from django_notification_rules import dispatch
from django_notification_rules.models import Delivery, Event, InboxMessage

pytestmark = pytest.mark.django_db


def test_a_rule_notifies_its_recipients_through_its_channels(make_rule, member, emit, outbox):
    ann, bob = member("ann"), member("bob")
    make_rule(
        channels=("memory", "inbox"),
        recipients=[("user", ann), ("user", bob)],
        templates={("*", ""): ("Order {{ number }}", "for {{ recipient.username }}", "")},
    )

    emit("orders.placed", number="A-1", amount="5")

    assert [(m["recipient"].username, m["subject"], m["body"]) for m in outbox] == [
        ("ann", "Order A-1", "for ann"),
        ("bob", "Order A-1", "for bob"),
    ]
    assert [(m.user.username, m.subject) for m in InboxMessage.objects.order_by("id")] == [
        ("ann", "Order A-1"),
        ("bob", "Order A-1"),
    ]
    assert Delivery.objects.filter(status="sent").count() == 4
    assert Delivery.objects.get(channel="inbox", recipient=ann).inbox_message.body == "for ann"


def test_only_the_rules_whose_condition_holds(make_rule, member, emit, outbox):
    ann = member("ann")
    make_rule("big", recipients=[("user", ann)], condition={"field": "amount", "op": "gte", "value": "100"})
    make_rule("all", recipients=[("user", ann)])
    make_rule("off", recipients=[("user", ann)], enabled=False)
    make_rule("other", event="orders.shipped", recipients=[("user", ann)])

    emit("orders.placed", number="A-1", amount="5")

    assert [d.rule.name for d in Delivery.objects.all()] == ["all"]


def test_a_channel_that_s_not_set_up_is_skipped(make_rule, member, emit, outbox):
    ann = member("ann")
    make_rule(channels=("sms", "memory"), recipients=[("user", ann)])

    emit("orders.placed", number="A-1", amount="5")

    skipped = Delivery.objects.get(channel="sms")
    assert (skipped.status, skipped.recipient) == ("skipped", None)
    assert "No channel 'sms'" in skipped.error
    assert len(outbox) == 1


def test_a_failing_channel_fails_its_delivery_only(make_rule, member, emit, outbox, settings):
    settings.NOTIFICATION_RULES = {
        **settings.NOTIFICATION_RULES,
        "CHANNELS": {
            **settings.NOTIFICATION_RULES["CHANNELS"],
            "down": {"BACKEND": "django_notification_rules.channels.memory.MemoryChannel", "FAIL": "gateway down"},
        },
    }
    ann = member("ann")
    make_rule(channels=("down", "memory"), recipients=[("user", ann)])

    emit("orders.placed", number="A-1", amount="5")

    failed = Delivery.objects.get(channel="down")
    assert (failed.status, failed.error, failed.attempts) == ("failed", "gateway down", 1)
    assert Delivery.objects.get(channel="memory").status == "sent"


def test_a_failed_delivery_is_sent_again(make_rule, member, emit, outbox, settings):
    channels = settings.NOTIFICATION_RULES["CHANNELS"]
    settings.NOTIFICATION_RULES = {
        **settings.NOTIFICATION_RULES,
        "CHANNELS": {**channels, "memory": {**channels["memory"], "FAIL": "down"}},
    }
    make_rule(recipients=[("user", member("ann"))])
    emit("orders.placed", number="A-1", amount="5")
    failed = Delivery.objects.get()
    settings.NOTIFICATION_RULES = {**settings.NOTIFICATION_RULES, "CHANNELS": channels}

    dispatch.send(failed)

    failed.refresh_from_db()
    assert (failed.status, failed.error, failed.attempts, failed.sent_at is not None) == ("sent", "", 2, True)
    assert len(outbox) == 1


def test_a_template_that_fails_fails_its_delivery(make_rule, member, emit, outbox):
    make_rule(recipients=[("user", member("ann"))], templates={("*", ""): ("", "{% extends 'x.html' %}", "")})

    emit("orders.placed", number="A-1", amount="5")

    failed = Delivery.objects.get()
    assert failed.status == "failed" and failed.error.startswith("Template:")
    assert outbox == []


def test_a_channel_that_writes_once_per_event(make_rule, member, emit, settings):
    settings.NOTIFICATION_RULES = {
        **settings.NOTIFICATION_RULES,
        "CHANNELS": {**settings.NOTIFICATION_RULES["CHANNELS"], "room": {"BACKEND": "tests.test_dispatch.RoomChannel"}},
    }
    make_rule(channels=("room",), recipients=[("user", member("ann")), ("user", member("bob"))])

    emit("orders.placed", number="A-1", amount="5")

    assert [(d.channel, d.recipient) for d in Delivery.objects.all()] == [("room", None)]
    assert ROOM == ["Order placed"]


ROOM: list = []


class RoomChannel:
    per_recipient = False

    def __init__(self, code, **options):
        self.code = code

    def send(self, delivery):
        ROOM.append(delivery.subject)


def test_an_event_is_processed_once(make_rule, member, emit, outbox):
    make_rule(recipients=[("user", member("ann"))])
    emit("orders.placed", number="A-1", amount="5")

    assert dispatch.process(Event.objects.get().pk) == []
    assert dispatch.process(999) == []
    assert len(outbox) == 1


def test_an_event_of_an_unknown_type_is_marked(db):
    gone = Event.objects.create(code="gone", payload={})

    dispatch.process(gone.pk)

    gone.refresh_from_db()
    assert gone.processed_at is not None and "No event type 'gone'" in gone.error


def test_a_condition_that_raises_skips_its_rule(make_rule, member, emit, monkeypatch, outbox):
    make_rule(recipients=[("user", member("ann"))])
    monkeypatch.setattr(dispatch.conditions, "matches", lambda *a: 1 / 0)

    emit("orders.placed", number="A-1", amount="5")

    assert outbox == [] and Event.objects.get().processed_at <= timezone.now()


def test_the_recipients_are_found_once_per_rule(make_rule, member, emit, monkeypatch, outbox):
    calls = []
    original = dispatch.recipients.resolve
    monkeypatch.setattr(dispatch.recipients, "resolve", lambda specs, event: calls.append(1) or original(specs, event))
    make_rule(channels=("memory", "inbox"), recipients=[("user", member("ann"))])

    emit("orders.placed", number="A-1", amount="5")

    assert calls == [1]
