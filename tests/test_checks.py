import pytest
from django.core import checks

from django_notification_rules.models import NotificationRule, RuleRecipient, RuleTemplate


def ids(databases=None):
    return sorted(m.id for m in checks.run_checks(databases=databases) if m.id.startswith("django_notification_rules."))


def test_the_test_settings_are_fine():
    assert ids() == []


def test_a_channel_without_a_backend_or_not_importable(settings):
    settings.NOTIFICATION_RULES = {
        **settings.NOTIFICATION_RULES,
        "CHANNELS": {"a": {}, "b": {"BACKEND": "no.such.Channel"}},
    }

    assert ids() == ["django_notification_rules.E001", "django_notification_rules.E001"]


def test_a_runner_or_language_function_not_importable(settings):
    settings.NOTIFICATION_RULES = {
        **settings.NOTIFICATION_RULES,
        "RUNNER": "no.such.run",
        "USER_LANGUAGE": "no.such.language",
    }

    assert ids() == ["django_notification_rules.E002", "django_notification_rules.E002"]


def test_the_cache(settings):
    settings.NOTIFICATION_RULES = {**settings.NOTIFICATION_RULES, "CACHE": "rules"}
    assert ids() == ["django_notification_rules.W001"]

    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "rules": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    }
    assert ids() == ["django_notification_rules.W002"]

    settings.CACHES = {**settings.CACHES, "rules": {"BACKEND": "django.core.cache.backends.db.DatabaseCache"}}
    assert ids() == []


@pytest.mark.django_db
def test_the_stored_rules(make_rule):
    make_rule("unknown event", event="gone")
    make_rule("bad condition", condition={"field": "nope", "op": "eq", "value": 1})
    rule = make_rule("bad parts", channels=("sms", "memory"))
    RuleRecipient.objects.create(rule=rule, kind="resolver", value="gone")
    RuleRecipient.objects.create(rule=rule, kind="permission", value="no.such_perm")
    RuleRecipient.objects.create(rule=rule, kind="permission", value="django_notification_rules.view_event")
    RuleTemplate.objects.create(rule=rule, body="{% if %}")
    NotificationRule.objects.create(name="fine", event_code="orders.placed")

    assert ids(["default"]) == [
        "django_notification_rules.E101",
        "django_notification_rules.E101",
        "django_notification_rules.W101",
        "django_notification_rules.W102",
        "django_notification_rules.W103",
        "django_notification_rules.W103",
    ]
    assert ids() == []  # without the database, the stored rules aren't read
