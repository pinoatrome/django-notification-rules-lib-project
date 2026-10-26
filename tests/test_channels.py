import logging

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_notification_rules import channels
from django_notification_rules.channels.base import BaseChannel
from django_notification_rules.models import Delivery, Event

pytestmark = pytest.mark.django_db


def delivery(user=None, **fields):
    event = Event.objects.create(code="orders.placed", payload={})
    return Delivery.objects.create(
        event=event, channel="x", recipient=user, subject="Hi", body="Body", link="/l", language="en", **fields
    )


def test_the_channels_set_up():
    assert channels.codes() == ["inbox", "memory", "console"]
    assert ("memory", "memory — Memory (tests)") in channels.choices()


def test_a_channel_not_set_up_or_not_importable(settings):
    with pytest.raises(channels.ChannelError):
        channels.get("sms")
    settings.NOTIFICATION_RULES = {**settings.NOTIFICATION_RULES, "CHANNELS": {"bad": {"BACKEND": "no.such.Backend"}}}
    with pytest.raises(ImproperlyConfigured, match="can't import"):
        channels.get("bad")
    assert channels.choices() == [("bad", "bad")]


def test_none_is_required(settings):
    settings.NOTIFICATION_RULES = {"CHANNELS": {}}

    assert channels.codes() == []


def test_the_console_writes_to_stdout_stderr_or_the_log(member, capsys, caplog):
    sent = delivery(member("ann"))

    channels.get("console").send(sent)
    channels.BaseChannel  # noqa: B018
    from django_notification_rules.channels.console import ConsoleChannel

    ConsoleChannel("console", STREAM="stderr").send(sent)
    with caplog.at_level(logging.INFO, logger="django_notification_rules.console"):
        ConsoleChannel("console", STREAM="log").send(delivery())

    out, err = capsys.readouterr()
    assert "[console] orders.placed → ann (en)\nHi\nBody\n/l" in out
    assert "→ ann" in err
    assert "→ -" in caplog.text


def test_the_inbox_needs_a_recipient():
    with pytest.raises(channels.ChannelError):
        channels.get("inbox").send(delivery())


def test_the_base_channel_is_abstract():
    with pytest.raises(NotImplementedError):
        BaseChannel("x").send(None)
