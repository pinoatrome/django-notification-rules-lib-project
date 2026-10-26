import pytest

pytest.importorskip("rest_framework")

from django.contrib.auth.models import Permission
from django.urls import reverse
from rest_framework.test import APIClient

from django_notification_rules.models import InboxMessage

pytestmark = pytest.mark.django_db

INBOX = "django_notification_rules:inbox-message"


def client_of(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_the_inbox_is_the_user_s_own(member):
    ann, bob = member("ann"), member("bob")
    first = InboxMessage.objects.create(user=ann, event_code="orders.placed", subject="One")
    InboxMessage.objects.create(user=ann, event_code="orders.placed", subject="Two")
    other = InboxMessage.objects.create(user=bob, event_code="orders.placed", subject="Bob's")
    api = client_of(ann)

    listed = api.get(reverse(f"{INBOX}-list")).data
    assert [m["subject"] for m in listed] == ["Two", "One"]
    assert api.get(reverse(f"{INBOX}-detail", args=[other.pk])).status_code == 404
    assert api.get(reverse(f"{INBOX}-unread-count")).data == {"unread": 2}

    read = api.post(reverse(f"{INBOX}-read", args=[first.pk])).data
    assert read["read"] is True
    assert api.post(reverse(f"{INBOX}-read", args=[first.pk])).data["read_at"] == read["read_at"]
    assert [m["subject"] for m in api.get(reverse(f"{INBOX}-list"), {"unread": "1"}).data] == ["Two"]

    assert api.post(reverse(f"{INBOX}-read-all")).data == {"marked": 1}
    assert api.get(reverse(f"{INBOX}-unread-count")).data == {"unread": 0}
    assert InboxMessage.objects.get(pk=other.pk).read_at is None


def test_the_inbox_needs_a_signed_in_user():
    assert APIClient().get(reverse(f"{INBOX}-list")).status_code in (401, 403)


def test_the_catalogue_for_who_may_view_the_rules(member):
    ann = member("ann")
    assert client_of(ann).get(reverse("django_notification_rules:catalogue")).status_code == 403
    ann.user_permissions.add(Permission.objects.get(codename="view_notificationrule"))
    ann = type(ann).objects.get(pk=ann.pk)

    catalogue = client_of(ann).get(reverse("django_notification_rules:catalogue")).data

    placed = next(e for e in catalogue["events"] if e["code"] == "orders.placed")
    assert placed["description"] == "A customer placed an order."
    assert placed["sample"]["number"] == "A-1"
    assert placed["templates"]["*"]["subject"] == "Order placed"
    assert "gte" in placed["operators"]["decimal"]
    assert {"code": "customer", "description": "The order's customer (the user named in the payload)."} in catalogue[
        "resolvers"
    ]
    assert [c["code"] for c in catalogue["channels"]] == ["inbox", "memory", "console"]
    assert catalogue["recipient_kinds"] == ["user", "group", "permission", "resolver"]
