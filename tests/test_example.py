"""The README's example, run: what it says happens does."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from django_notification_rules.events import Field, event
from django_notification_rules.models import Delivery, InboxMessage
from django_notification_rules.recipients import recipients
from django_notification_rules.yaml_io import load_rules, parse_yaml
from tests.settings import DRF

RULES = """
rules:
  - name: Big orders to the sales team
    event: shop.order_placed
    condition: {field: amount, op: gte, value: "1000"}
    recipients: [{group: SALES}]
    channels: [inbox, console]
    templates:
      - channel: "*"
        language: ""
        subject: "Big order {{ number }}"
        body: "{{ amount }} EUR from {{ customer }}"
        link: "/admin/shop/order/{{ order_id }}/"

  - name: Order confirmation
    event: shop.order_placed
    recipients: [{resolver: order_customer}]
    channels: [inbox]
    templates:
      - {channel: "*", language: "", subject: "Order {{ number }} received",
         body: "Thank you, {{ recipient.first_name }}: we're preparing your order of {{ amount }} EUR."}
      - {channel: "*", language: "it", subject: "Ordine {{ number }} ricevuto",
         body: "Grazie, {{ recipient.first_name }}: stiamo preparando il tuo ordine di {{ amount }} EUR."}
"""


def language_of(user):
    return "it" if user.username == "ann" else "en"


@pytest.fixture
def shop(db, member, settings):
    @event(
        "shop.order_placed",
        fields={
            "number": Field("str"),
            "amount": Field("decimal"),
            "customer": Field("str"),
            "order_id": Field("int"),
        },
    )
    def order_placed():
        """A customer placed an order."""
        return {"number": "A-1042", "amount": "1250.00", "customer": "ann", "order_id": 42}

    @recipients("order_customer")
    def order_customer(event):
        """The customer who placed the order."""
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(username=event.data["customer"])

    settings.NOTIFICATION_RULES = {**settings.NOTIFICATION_RULES, "USER_LANGUAGE": "tests.test_example.language_of"}
    member("ann", first_name="Ann")
    member("bob", "SALES", first_name="Bob")
    load_rules(parse_yaml(RULES))
    return Group.objects.get(name="SALES")


def test_a_big_order_alerts_the_sales_team_and_confirms_to_its_customer(shop, emit, capsys):
    emit("shop.order_placed", number="A-1042", amount=Decimal("1250.00"), customer="ann", order_id=42)

    assert capsys.readouterr().out == (
        "[console] shop.order_placed → bob (en)\nBig order A-1042\n1250.00 EUR from ann\n/admin/shop/order/42/\n\n"
    )
    inbox = {m.user.username: (m.subject, m.body, m.link) for m in InboxMessage.objects.all()}
    assert inbox == {
        "bob": ("Big order A-1042", "1250.00 EUR from ann", "/admin/shop/order/42/"),
        "ann": ("Ordine A-1042 ricevuto", "Grazie, Ann: stiamo preparando il tuo ordine di 1250,00 EUR.", ""),
    }
    assert Delivery.objects.filter(status="sent").count() == 3


def test_a_small_order_only_confirms(shop, emit, capsys):
    emit("shop.order_placed", number="A-1043", amount=Decimal("80"), customer="ann", order_id=43)

    assert capsys.readouterr().out == ""
    assert [m.user.username for m in InboxMessage.objects.all()] == ["ann"]


@pytest.mark.skipif(not DRF, reason="the REST API needs Django REST framework")
def test_the_customer_reads_it_from_the_api(shop, emit):
    from rest_framework.test import APIClient

    emit("shop.order_placed", number="A-1042", amount=Decimal("1250.00"), customer="ann", order_id=42)
    client = APIClient()
    client.force_authenticate(InboxMessage.objects.get(user__username="ann").user)

    [message] = client.get(reverse("django_notification_rules:inbox-message-list"), {"unread": "1"}).data

    assert (message["event_code"], message["subject"], message["read"]) == (
        "shop.order_placed",
        "Ordine A-1042 ricevuto",
        False,
    )
