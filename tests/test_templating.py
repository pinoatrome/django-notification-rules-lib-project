import pytest
from django.contrib.auth.models import AnonymousUser

from django_notification_rules import templating
from django_notification_rules.models import Event

pytestmark = pytest.mark.django_db


def placed(**payload):
    return Event.objects.create(
        code="orders.placed", payload={"number": "A-1", "amount": "1234.5", "customer": "ann", **payload}
    )


def template(channel="*", language="", subject="", body="", link=""):
    return {"channel": channel, "language": language, "subject": subject, "body": body, "link": link}


def test_the_payload_parsed_and_the_recipient(member):
    ann = member("ann", first_name="Ann", last_name="Lee", email="ann@example.com")

    text = templating.text_for(
        [
            template(
                subject="Hi {{ recipient.first_name }}",
                body="{{ amount|floatformat:2 }} for {{ number }}",
                link="/o/{{ number }}",
            )
        ],
        "inbox",
        placed(),
        ann,
    )

    assert (text.subject, text.body, text.link, text.language) == ("Hi Ann", "1234.50 for A-1", "/o/A-1", "en")


def test_the_event_s_own_texts_when_the_rule_has_none(member):
    text = templating.text_for([], "inbox", placed(), member("ann"))

    assert (text.subject, text.body, text.link) == ("Order placed", "Order A-1: 1234.5", "/orders/A-1")


def test_the_event_s_description_when_no_one_wrote_texts(member):
    shipped = Event.objects.create(code="orders.shipped", payload={"number": "A-1", "carrier": "ups"})

    assert templating.text_for([], "inbox", shipped, member("ann")).subject == "An order left the warehouse."
    assert templating.text_for([], "inbox", Event(code="gone", payload={}), None).subject == "gone"


def test_the_template_for_the_channel_and_language_first():
    templates = [
        template("*", "", "any"),
        template("*", "it", "any it"),
        template("inbox", "", "inbox"),
        template("inbox", "pt", "inbox pt"),
    ]

    assert templating.pick(templates, "inbox", "pt-br")["subject"] == "inbox pt"
    assert templating.pick(templates, "inbox", "it")["subject"] == "inbox"
    assert templating.pick(templates, "memory", "it")["subject"] == "any it"
    assert templating.pick(templates, "memory", "de")["subject"] == "any"
    assert templating.pick([], "memory", "de") is None


def test_the_recipient_s_language(member, settings):
    settings.NOTIFICATION_RULES = {**settings.NOTIFICATION_RULES, "USER_LANGUAGE": "tests.test_templating.italian"}
    ann = member("ann")

    text = templating.text_for(
        [template(language="it", subject="Ordine {{ number }}"), template(subject="Order")], "inbox", placed(), ann
    )

    assert (text.subject, text.language) == ("Ordine A-1", "it")


def italian(user):
    return "it"


def test_no_recipient_writes_in_the_project_s_language():
    assert templating.text_for([template(subject="{{ recipient.username }}x")], "memory", placed(), None).subject == "x"


def test_nothing_is_escaped(member):
    text = templating.text_for([template(body="{{ customer }}")], "inbox", placed(customer="<Ann & Co>"), member("a"))

    assert text.body == "<Ann & Co>"


@pytest.mark.parametrize(
    "source",
    [
        "{% load static %}",
        "{% include 'x.html' %}",
        "{% extends 'b.html' %}",
        "{% debug %}",
        "{% if %}",
        "{{ a|nofilter }}",
    ],
)
def test_no_libraries_no_loaders_and_bad_syntax_are_refused(source):
    with pytest.raises(templating.TemplateError):
        templating.check(source)


def test_a_template_that_fails_fails_its_text(member):
    with pytest.raises(templating.TemplateError):
        templating.text_for([template(body="{% extends 'base.html' %}")], "inbox", placed(), member("ann"))


def test_the_recipient_context_never_holds_the_user():
    assert templating.recipient_context(None) == {}
    assert set(templating.recipient_context(AnonymousUser())) == {
        "username",
        "first_name",
        "last_name",
        "full_name",
        "email",
    }
