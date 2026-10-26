import pytest
from django.core.cache import caches

from django_notification_rules import cache
from django_notification_rules.models import RuleChannel, RuleTemplate

pytestmark = pytest.mark.django_db


@pytest.fixture
def cached(settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "nr"}}
    settings.NOTIFICATION_RULES = {**settings.NOTIFICATION_RULES, "CACHE": "default"}
    caches["default"].clear()
    yield caches["default"]
    caches["default"].clear()


def test_without_a_cache_the_database_each_time(make_rule):
    make_rule("a")

    assert [r["name"] for r in cache.rules_for("orders.placed")] == ["a"]
    cache.forget("orders.placed")  # nothing to drop


def test_the_rules_as_the_dispatcher_reads_them(make_rule, member):
    ann = member("ann")
    rule = make_rule("a", channels=("memory", "inbox"), recipients=[("user", ann)],
                     templates={("inbox", "it"): ("S", "B", "L")}, condition={"field": "number", "op": "eq", "value": "x"})
    RuleChannel.objects.filter(rule=rule, channel="inbox").update(enabled=False)

    [read] = cache.rules_for("orders.placed")

    assert read == {"id": rule.pk, "name": "a", "condition": {"field": "number", "op": "eq", "value": "x"},
                    "recipients": [{"kind": "user", "user_id": ann.pk, "group_id": None, "value": ""}],
                    "channels": ["memory"],
                    "templates": [{"channel": "inbox", "language": "it", "subject": "S", "body": "B", "link": "L"}]}


def test_kept_in_the_cache_and_dropped_once_a_rule_changes(cached, make_rule, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        rule = make_rule("a")
    assert [r["name"] for r in cache.rules_for("orders.placed")] == ["a"]
    assert cached.get(cache.KEY.format(code="orders.placed")) is not None

    with django_capture_on_commit_callbacks(execute=True):
        RuleTemplate.objects.create(rule=rule, subject="new")
    assert cached.get(cache.KEY.format(code="orders.placed")) is None
    assert cache.rules_for("orders.placed")[0]["templates"][0]["subject"] == "new"

    with django_capture_on_commit_callbacks(execute=True):
        rule.event_code = "orders.shipped"
        rule.save()
    assert cache.rules_for("orders.placed") == []
    assert [r["name"] for r in cache.rules_for("orders.shipped")] == ["a"]


def test_forget_without_codes_drops_every_event_type_s(cached, make_rule):
    make_rule("a", event="custom.code")
    cache.rules_for("custom.code")
    cache.rules_for("orders.placed")

    cache.forget()

    assert cached.get(cache.KEY.format(code="custom.code")) is None
    assert cached.get(cache.KEY.format(code="orders.placed")) is None
