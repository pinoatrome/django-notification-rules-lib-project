import json

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from django_notification_rules.models import Delivery, Event, InboxMessage, NotificationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(admin_client):
    return admin_client


def url(name, *args):
    return reverse(f"admin:django_notification_rules_notificationrule_{name}", args=args)


def test_the_rule_list_and_its_tools(admin, make_rule):
    make_rule("Big orders", channels=("memory", "inbox"))

    page = admin.get(url("changelist")).content.decode()

    assert "Big orders" in page and "memory, inbox" in page
    for tool in ("overview", "check", "export", "load"):
        assert url(tool) in page


def test_a_rule_s_form_offers_the_events_channels_and_condition_builder(admin, make_rule):
    rule = make_rule(event="gone", channels=("sms",))

    page = admin.get(url("change", rule.pk)).content.decode()

    assert "orders.placed — A customer placed an order." in page
    assert "gone (unknown)" in page and "sms (unknown)" in page
    assert "condition.js" in page and "nr-condition" in page and '"orders.shipped"' in page
    assert '<option value="customer">' in page  # the resolvers' datalist
    assert url("preview", rule.pk) in page


def test_a_rule_is_added_with_its_parts(admin, member):
    ann = member("ann")
    data = {
        "name": "New",
        "event_code": "orders.placed",
        "description": "",
        "enabled": "on",
        "condition": json.dumps({"all": [{"field": "amount", "op": "gte", "value": "10"}]}),
        "recipients-TOTAL_FORMS": "1",
        "recipients-INITIAL_FORMS": "0",
        "recipients-0-kind": "user",
        "recipients-0-user": ann.pk,
        "channels-TOTAL_FORMS": "1",
        "channels-INITIAL_FORMS": "0",
        "channels-0-channel": "inbox",
        "channels-0-enabled": "on",
        "templates-TOTAL_FORMS": "1",
        "templates-INITIAL_FORMS": "0",
        "templates-0-channel": "*",
        "templates-0-language": "it",
        "templates-0-subject": "Ordine {{ number }}",
        "templates-0-body": "",
        "templates-0-link": "",
    }

    response = admin.post(url("add"), data)

    assert response.status_code == 302, response.content.decode()[:2000]
    rule = NotificationRule.objects.get(name="New")
    assert rule.condition == {"all": [{"field": "amount", "op": "gte", "value": "10"}]}
    assert [r.user for r in rule.recipients.all()] == [ann]
    assert [(t.channel, t.language) for t in rule.templates.all()] == [("*", "it")]


def test_a_bad_condition_is_refused(admin):
    response = admin.post(
        url("add"),
        {
            "name": "Bad",
            "event_code": "orders.placed",
            "condition": '{"field": "nope", "op": "eq"}',
            **{
                f"{p}-{k}": "0"
                for p in ("recipients", "channels", "templates")
                for k in ("TOTAL_FORMS", "INITIAL_FORMS")
            },
        },
    )

    assert response.status_code == 200
    assert "has no field" in response.content.decode()


def test_the_overview(admin, make_rule, member):
    make_rule("Big", channels=("memory",), recipients=[("user", member("ann"))])
    make_rule("Lost", event="gone", enabled=False)

    page = admin.get(url("overview")).content.decode()

    assert "orders.placed" in page and "Big" in page and "user ann" in page
    assert "orders.shipped" in page and "No rule: nobody is notified." in page
    assert "not declared by the code" in page and "Lost" in page


def test_preview_and_test_send(admin, make_rule, admin_user, outbox):
    rule = make_rule(templates={("*", ""): ("Order {{ number }}", "{{ amount }} for {{ recipient.username }}", "")})

    page = admin.get(url("preview", rule.pk)).content.decode()
    assert "A-1" in page  # the sample payload

    payload = json.dumps({"number": "Z-9", "amount": "3"})
    preview = admin.post(url("preview", rule.pk), {"channel": "memory", "language": "en", "payload": payload})
    assert "Order Z-9" in preview.content.decode() and "3 for admin" in preview.content.decode()
    assert outbox == [] and not Event.objects.exists()

    sent = admin.post(url("preview", rule.pk), {"channel": "memory", "language": "en", "payload": payload, "send": "1"})
    assert "Test send:" in sent.content.decode()
    assert [(m["recipient"], m["subject"]) for m in outbox] == [(admin_user, "Order Z-9")]
    assert Event.objects.get().error == "test send" and Delivery.objects.get().status == "sent"


def test_preview_refuses_a_bad_payload_and_shows_a_template_error(admin, make_rule):
    rule = make_rule(templates={("*", ""): ("", "{% now %}", "")})

    bad = admin.post(url("preview", rule.pk), {"channel": "memory", "language": "en", "payload": "{"})
    assert "errorlist" in bad.content.decode()

    failing = admin.post(
        url("preview", rule.pk),
        {"channel": "memory", "language": "en", "payload": json.dumps({"number": "A", "amount": "1"})},
    )
    assert "errornote" in failing.content.decode()


def test_preview_of_a_rule_of_an_unknown_event(admin, make_rule):
    assert admin.get(url("preview", make_rule(event="gone").pk)).status_code == 200


def test_export_and_load(admin, make_rule):
    make_rule("Big")

    exported = admin.get(url("export"))
    assert exported["Content-Type"].startswith("application/yaml") and b"Big" in exported.content

    loaded = admin.post(url("load"), {"document": "rules: [{name: Small, event: orders.placed}]"})
    assert loaded.status_code == 302
    assert list(NotificationRule.objects.values_list("name", flat=True)) == ["Small"]

    refused = admin.post(url("load"), {"document": "rules: [{name: x}]"})
    assert "Nothing was stored." in refused.content.decode()


def test_load_from_a_file(admin):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("rules.yaml", b"rules: [{name: Up, event: orders.placed}]")

    assert admin.post(url("load"), {"file": upload, "keep": "on"}).status_code == 302
    assert NotificationRule.objects.filter(name="Up").exists()


def test_check_configuration(admin, make_rule):
    assert "are fine" in admin.get(url("check")).content.decode()
    make_rule(event="gone")
    assert "W101" in admin.get(url("check")).content.decode()


def test_a_staff_member_with_the_view_permission_only(client, django_user_model, make_rule):
    clerk = django_user_model.objects.create_user("clerk", password="x", is_staff=True)
    clerk.user_permissions.add(Permission.objects.get(codename="view_notificationrule"))
    client.force_login(clerk)
    rule = make_rule()

    assert client.get(url("overview")).status_code == 200
    assert client.get(url("load")).status_code == 403
    sent = client.post(
        url("preview", rule.pk),
        {"channel": "memory", "language": "en", "send": "1", "payload": json.dumps({"number": "A", "amount": "1"})},
    )
    assert sent.status_code == 403


def test_a_staff_member_without_permissions(client, django_user_model, make_rule):
    client.force_login(django_user_model.objects.create_user("nobody", password="x", is_staff=True))
    rule = make_rule()

    for target in (url("overview"), url("export"), url("check"), url("preview", rule.pk)):
        assert client.get(target).status_code == 403, target


def test_events_deliveries_and_inbox_pages(admin, make_rule, member, emit, settings):
    channels = settings.NOTIFICATION_RULES["CHANNELS"]
    settings.NOTIFICATION_RULES = {
        **settings.NOTIFICATION_RULES,
        "CHANNELS": {**channels, "memory": {**channels["memory"], "FAIL": "down"}},
    }
    make_rule(channels=("memory", "inbox"), recipients=[("user", member("ann"))])
    emit("orders.placed", number="A-1", amount="5")
    event = Event.objects.get()

    assert (
        "down" in admin.get(reverse("admin:django_notification_rules_event_change", args=[event.pk])).content.decode()
    )
    deliveries = admin.get(reverse("admin:django_notification_rules_delivery_changelist")).content.decode()
    assert "failed" in deliveries
    assert admin.get(reverse("admin:django_notification_rules_inboxmessage_changelist")).status_code == 200
    assert admin.get(reverse("admin:django_notification_rules_event_changelist")).status_code == 200

    settings.NOTIFICATION_RULES = {**settings.NOTIFICATION_RULES, "CHANNELS": channels}
    failed = Delivery.objects.get(status="failed")
    admin.post(
        reverse("admin:django_notification_rules_delivery_changelist"),
        {"action": "send_again", "_selected_action": [failed.pk]},
    )
    failed.refresh_from_db()
    assert failed.status == "sent" and failed.attempts == 2
    assert InboxMessage.objects.count() == 1
