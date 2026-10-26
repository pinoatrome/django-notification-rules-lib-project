import datetime
from decimal import Decimal

import pytest
from django.db.models.signals import Signal

from django_notification_rules import events
from django_notification_rules.events import Field
from django_notification_rules.models import Event


def test_the_apps_event_types_are_discovered():
    placed = events.get("orders.placed")

    assert placed.description == "A customer placed an order."  # the sample function's docstring
    assert placed.module == "tests.events"
    assert set(placed.fields) == {"number", "amount", "customer", "urgent", "due"}
    assert ("orders.shipped", "orders.shipped — An order left the warehouse.") in events.choices()


def test_an_unknown_event_type_is_refused():
    with pytest.raises(events.UnknownEvent):
        events.get("nope")


@pytest.mark.parametrize(
    ("spec", "value", "stored"),
    [
        (Field("str"), 12, "12"),
        (Field("int"), "7", 7),
        (Field("decimal"), Decimal("12.5"), "12.5"),
        (Field("decimal"), 3, "3"),
        (Field("bool"), True, True),
        (Field("date"), datetime.date(2026, 1, 2), "2026-01-02"),
        (Field("date"), datetime.datetime(2026, 1, 2, 10, 0), "2026-01-02"),
        (Field("date"), "2026-01-02", "2026-01-02"),
        (Field("datetime"), datetime.datetime(2026, 1, 2, 10, 0, tzinfo=datetime.UTC), "2026-01-02T10:00:00+00:00"),
        (Field("str"), None, None),
    ],
)
def test_a_value_is_stored_as_json(spec, value, stored):
    assert spec.dump(value) == stored


@pytest.mark.parametrize(("spec", "value"), [(Field("int"), True), (Field("int"), "x"), (Field("decimal"), "x"),
                                             (Field("bool"), "yes"), (Field("date"), "tomorrow")])
def test_a_value_of_the_wrong_type_is_refused(spec, value):
    with pytest.raises(events.PayloadError):
        spec.dump(value)


def test_a_field_type_must_be_known():
    with pytest.raises(ValueError, match="Unknown field type"):
        Field("money")


@pytest.mark.parametrize(
    ("spec", "raw", "parsed"),
    [
        (Field("int"), "3", 3),
        (Field("bool"), "true", True),
        (Field("bool"), False, False),
        (Field("date"), datetime.datetime(2026, 1, 2, 3, 4), datetime.date(2026, 1, 2)),
        (Field("date"), datetime.date(2026, 1, 2), datetime.date(2026, 1, 2)),
        (Field("datetime"), "2026-01-02T03:04:00+00:00", datetime.datetime(2026, 1, 2, 3, 4, tzinfo=datetime.UTC)),
        (Field("datetime"), datetime.datetime(2026, 1, 2), datetime.datetime(2026, 1, 2)),
        (Field("str"), "", None),
    ],
)
def test_a_stored_value_is_read_back(spec, raw, parsed):
    assert spec.parse(raw) == parsed


def test_a_payload_is_checked_against_the_fields():
    placed = events.get("orders.placed")

    assert placed.dump({"number": "A-1", "amount": Decimal("9.90")}) == {
        "number": "A-1", "amount": "9.90", "customer": None, "urgent": None, "due": None}
    with pytest.raises(events.PayloadError, match="needs number"):
        placed.dump({"amount": "1"})
    with pytest.raises(events.PayloadError, match="unknown payload fields colour"):
        placed.dump({"number": "A-1", "amount": "1", "colour": "red"})
    with pytest.raises(events.PayloadError, match=r"orders.placed.amount"):
        placed.dump({"number": "A-1", "amount": "lots"})


def test_a_stored_payload_is_parsed_and_tolerates_bad_values():
    placed = events.get("orders.placed")

    assert placed.parse({"number": "A-1", "amount": "1.50", "due": "garbage"}) == {
        "number": "A-1", "amount": Decimal("1.50"), "customer": None, "urgent": None, "due": "garbage"}


def test_the_sample_payload_is_the_code_s_or_made_up():
    assert events.get("orders.placed").sample_payload()["number"] == "A-1"
    assert events.get("orders.shipped").sample_payload() == {"number": "…", "carrier": "ups"}  # its function: None
    made_up = events.declare("x.y", fields={"n": Field("int"), "c": Field("str", choices=("a", "b"))})
    assert made_up.sample_payload() == {"n": 1, "c": "a"}


def test_the_default_texts_fall_back_to_any_channel():
    placed = events.get("orders.placed")

    assert str(placed.template("inbox")["subject"]) == "Order placed"
    assert events.get("orders.shipped").template("inbox") == {}


def test_event_and_recipient_are_reserved_names():
    with pytest.raises(ValueError, match="recipient"):
        events.declare("x.y", fields={"recipient": Field()})


@pytest.mark.django_db
def test_emit_records_the_event_after_the_commit(emit, member):
    ann = member("ann")

    emit("orders.placed", number="A-1", amount="5", actor=ann)

    recorded = Event.objects.get()
    assert (recorded.code, recorded.actor, recorded.processed_at is not None) == ("orders.placed", ann, True)
    assert recorded.payload["amount"] == "5"
    assert recorded.data["amount"] == Decimal("5")


@pytest.mark.django_db
def test_emit_checks_the_payload_at_once(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks() as callbacks, pytest.raises(events.PayloadError):
        events.emit("orders.placed", amount="5")
    assert callbacks == []


@pytest.mark.django_db
def test_an_event_of_a_type_no_longer_declared_keeps_its_payload():
    assert Event(code="gone", payload={"a": 1}).data == {"a": 1}


@pytest.mark.django_db
def test_a_signal_feeds_an_event_type(django_capture_on_commit_callbacks, member):
    ann = member("ann")
    placed = Signal()
    events.connect_signal(placed, "orders.placed",
                          lambda sender, order, **kw: None if order == "skip" else {"number": order, "amount": "1",
                                                                                    "actor": ann})

    with django_capture_on_commit_callbacks(execute=True):
        placed.send(sender=None, order="skip")
        placed.send(sender=None, order="B-2")

    assert [(e.payload["number"], e.actor) for e in Event.objects.all()] == [("B-2", ann)]
