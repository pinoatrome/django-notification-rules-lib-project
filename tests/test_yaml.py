import io

import pytest
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command

from django_notification_rules import yaml_io
from django_notification_rules.models import NotificationRule

pytestmark = pytest.mark.django_db

DOCUMENT = """
rules:
  - name: Big orders
    event: orders.placed
    description: To the sales team
    condition: {field: amount, op: gte, value: "1000"}
    recipients:
      - group: SALES
      - permission: django_notification_rules.view_notificationrule
      - resolver: customer
      - user: ann
    channels: {inbox: {}, memory: {enabled: false}}
    templates:
      - {channel: "*", language: "", subject: "Order {{ number }}", body: "for {{ amount }}", link: "/o/{{ number }}"}
      - {channel: inbox, language: it, subject: "Ordine {{ number }}"}
  - name: Shipped
    event: orders.shipped
    enabled: false
    recipients: [{resolver: actor}]
    channels: [memory]
"""


def test_a_document_is_stored_and_exported_back(member):
    member("ann")

    result = yaml_io.load_rules(yaml_io.parse_yaml(DOCUMENT))

    assert result == {"stored": ["Big orders", "Shipped"], "deleted": []}
    assert Group.objects.filter(name="SALES").exists()
    exported = yaml_io.export_rules()["rules"]
    assert exported[0] == {
        "name": "Big orders",
        "event": "orders.placed",
        "description": "To the sales team",
        "enabled": True,
        "condition": {"field": "amount", "op": "gte", "value": "1000"},
        "recipients": [
            {"group": "SALES"},
            {"permission": "django_notification_rules.view_notificationrule"},
            {"resolver": "customer"},
            {"user": "ann"},
        ],
        "channels": {"inbox": {"enabled": True}, "memory": {"enabled": False}},
        "templates": [
            {
                "channel": "*",
                "language": "",
                "subject": "Order {{ number }}",
                "body": "for {{ amount }}",
                "link": "/o/{{ number }}",
            },
            {"channel": "inbox", "language": "it", "subject": "Ordine {{ number }}", "body": "", "link": ""},
        ],
    }
    assert exported[1] == {
        "name": "Shipped",
        "event": "orders.shipped",
        "enabled": False,
        "recipients": [{"resolver": "actor"}],
        "channels": ["memory"],
    }
    again = yaml_io.load_rules(yaml_io.parse_yaml(yaml_io.dump_yaml(yaml_io.export_rules())))
    assert again["stored"] == ["Big orders", "Shipped"]
    assert yaml_io.export_rules()["rules"] == exported


def test_the_rules_the_document_doesn_t_name_are_deleted_unless_kept(make_rule):
    make_rule("old")
    document = {"rules": [{"name": "new", "event": "orders.placed"}]}

    assert yaml_io.load_rules(document, keep=True)["deleted"] == []
    assert yaml_io.load_rules(document)["deleted"] == ["old"]
    assert list(NotificationRule.objects.values_list("name", flat=True)) == ["new"]


def test_a_bad_document_stores_nothing(make_rule):
    make_rule("old")
    bad = {
        "rules": [
            {"name": "x"},
            {"name": "y", "event": "nope"},
            {
                "name": "z",
                "event": "orders.placed",
                "condition": {"field": "nope", "op": "eq", "value": 1},
                "recipients": [{"user": "ghost"}, {"resolver": "nope"}, {"a": 1, "b": 2}],
                "templates": [{"body": "{% if %}"}],
            },
            {
                "name": "w",
                "event": "orders.placed",
                "recipients": [{"user": "ghost"}, {"resolver": "nope"}, {"a": 1, "b": 2}],
                "templates": [{"body": "{% if %}"}],
            },
        ]
    }

    with pytest.raises(yaml_io.RulesDocumentError) as raised:
        yaml_io.load_rules(bad)

    errors = raised.value.errors
    assert any("needs a name and an event" in e for e in errors)
    assert any("'y'" in e and "event_code" in e for e in errors)
    assert any("'z'" in e and "condition" in e for e in errors)
    assert any("no user 'ghost'" in e for e in errors)
    assert any("resolver 'nope'" in e for e in errors)
    assert any("a recipient is one of" in e for e in errors)
    assert any("template" in e for e in errors)
    assert list(NotificationRule.objects.values_list("name", flat=True)) == ["old"]


@pytest.mark.parametrize("document", [[], {"rules": "x"}])
def test_a_document_has_a_list_of_rules(document):
    with pytest.raises(yaml_io.RulesDocumentError):
        yaml_io.load_rules(document)


def test_not_yaml():
    with pytest.raises(yaml_io.RulesDocumentError, match="Not YAML"):
        yaml_io.parse_yaml("rules: [")
    assert yaml_io.parse_yaml("") == {}


def test_the_commands_load_and_export(tmp_path, member):
    member("ann")
    source = tmp_path / "rules.yaml"
    source.write_text(DOCUMENT)
    out = io.StringIO()

    call_command("notification_rules_load", str(source), stdout=out)
    assert "Stored 2 rules, deleted 0." in out.getvalue()

    target = tmp_path / "out.yaml"
    call_command("notification_rules_export", "-o", str(target))
    assert "Big orders" in target.read_text()
    printed = io.StringIO()
    call_command("notification_rules_export", stdout=printed)
    assert printed.getvalue() == target.read_text()

    (tmp_path / "one.yaml").write_text("rules: [{name: Big orders, event: orders.placed}]")
    out = io.StringIO()
    call_command("notification_rules_load", str(tmp_path / "one.yaml"), stdout=out)
    assert "deleted: Shipped" in out.getvalue()


def test_the_load_command_reads_the_standard_input_and_reports_errors(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("rules: [{name: x}]"))

    with pytest.raises(CommandError, match="needs a name and an event"):
        call_command("notification_rules_load", "-")
