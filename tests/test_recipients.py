import pytest
from django.contrib.auth.models import Group, Permission

from django_notification_rules import recipients
from django_notification_rules.models import Event

pytestmark = pytest.mark.django_db


def event(**payload):
    return Event.objects.create(code="orders.placed", payload={"number": "A-1", "amount": "1", **payload})


def users(specs, of=None):
    return [user.username for user in recipients.resolve(specs, of or event())]


def test_a_user_and_a_group(member):
    ann, _bob = member("ann"), member("bob", "STAFF")
    member("cid", "STAFF")
    staff = Group.objects.get(name="STAFF")

    assert users([{"kind": "user", "user_id": ann.pk}, {"kind": "group", "group_id": staff.pk}]) == ["ann", "bob", "cid"]


def test_each_user_once_and_the_inactive_never(member):
    ann = member("ann", "STAFF")
    member("old", "STAFF", is_active=False)
    staff = Group.objects.get(name="STAFF")

    assert users([{"kind": "group", "group_id": staff.pk}, {"kind": "user", "user_id": ann.pk}]) == ["ann"]


def test_the_holders_of_a_permission(member):
    clerk = member("clerk")
    clerk.user_permissions.add(Permission.objects.get(codename="view_notificationrule"))
    member("root", is_superuser=True)
    member("nobody")

    found = users([{"kind": "permission", "value": "django_notification_rules.view_notificationrule"}])

    assert sorted(found) == ["clerk", "root"]


def test_the_holders_of_a_permission_by_a_backend(member, settings):
    settings.NOTIFICATION_RULES = {**settings.NOTIFICATION_RULES,
                                   "PERMISSION_BACKEND": "django.contrib.auth.backends.ModelBackend"}
    member("root", is_superuser=True)

    assert users([{"kind": "permission", "value": "django_notification_rules.view_notificationrule"}]) == ["root"]


def test_a_resolver_from_the_event(member):
    member("ann")

    assert users([{"kind": "resolver", "value": "customer"}], event(customer="ann")) == ["ann"]
    assert users([{"kind": "resolver", "value": "customer"}], event()) == []


def test_the_actor_and_the_superusers(member):
    ann = member("ann")
    member("root", is_superuser=True)
    happened = Event.objects.create(code="orders.placed", payload={}, actor=ann)

    assert users([{"kind": "resolver", "value": "actor"}, {"kind": "resolver", "value": "superusers"}],
                 happened) == ["ann", "root"]
    assert users([{"kind": "resolver", "value": "actor"}]) == []


def test_a_failing_or_unknown_resolver_finds_no_one(member, caplog):
    ann = member("ann")

    found = users([{"kind": "resolver", "value": "broken"}, {"kind": "resolver", "value": "gone"},
                   {"kind": "user", "user_id": ann.pk}])

    assert found == ["ann"]
    assert "no customers today" in caplog.text and "no resolver 'gone'" in caplog.text


def test_an_unknown_kind_is_logged(caplog):
    assert users([{"kind": "robot"}]) == []
    assert "Unknown recipient kind" in caplog.text


def test_resolvers_are_declared_by_the_code():
    assert recipients.REGISTRY["customer"].fqn == "tests.recipients.customer"
    assert ("superusers", "superusers — The superusers.") in recipients.choices()

    @recipients.recipients()
    def nobody(event):
        return []

    assert recipients.REGISTRY["nobody"].description == ""


def test_describe(member):
    ann = member("ann", "STAFF")
    staff = Group.objects.get(name="STAFF")

    assert recipients.describe({"kind": "user", "user_id": ann.pk}) == "user ann"
    assert recipients.describe({"kind": "group", "group_id": staff.pk}) == "group STAFF"
    assert recipients.describe({"kind": "user", "user_id": 999}) == "user 999"
    assert recipients.describe({"kind": "resolver", "value": "customer"}) == "resolver customer"
