import pytest

from django_notification_rules import conditions, events

PLACED = {"number": "A-17", "amount": "120.00", "customer": "Ann", "urgent": True, "due": "2026-03-01"}


def holds(condition, payload=PLACED) -> bool:
    return conditions.matches(condition, events.get("orders.placed"), payload)


def test_an_empty_condition_holds():
    assert holds({}) and holds(None)


@pytest.mark.parametrize(
    ("field", "op", "value", "expected"),
    [
        ("amount", "gte", "120", True),
        ("amount", "gt", "120", False),
        ("amount", "lt", "200.5", True),
        ("amount", "lte", "119.99", False),
        ("amount", "eq", "120", True),
        ("amount", "ne", "120", False),
        ("amount", "in", ["1", "120.00"], True),
        ("amount", "not_in", "1, 2", True),
        ("number", "startswith", "a-", True),
        ("number", "endswith", "17", True),
        ("number", "contains", "-1", True),
        ("number", "not_contains", "B", True),
        ("urgent", "eq", "true", True),
        ("urgent", "ne", True, False),
        ("due", "lt", "2026-04-01", True),
        ("customer", "is_not_empty", None, True),
        ("customer", "is_empty", None, False),
    ],
)
def test_each_operator(field, op, value, expected):
    assert holds({"all": [{"field": field, "op": op, "value": value}]}) is expected


def test_a_single_test_needs_no_group():
    assert holds({"field": "number", "op": "eq", "value": "A-17"})


def test_groups_nest():
    condition = {"any": [{"field": "amount", "op": "gt", "value": "1000"},
                         {"all": [{"field": "urgent", "op": "eq", "value": True},
                                  {"field": "customer", "op": "eq", "value": "Ann"}]}]}

    assert holds(condition)
    assert not holds(condition, {**PLACED, "customer": "Bob"})


def test_a_missing_value_holds_only_as_empty():
    payload = {**PLACED, "customer": None}

    assert holds({"field": "customer", "op": "is_empty"}, payload)
    assert not holds({"field": "customer", "op": "startswith", "value": "A"}, payload)
    assert not holds({"field": "customer", "op": "eq", "value": "Ann"}, payload)


def test_what_can_t_be_compared_doesn_t_hold():
    assert not holds({"field": "nope", "op": "eq", "value": 1})
    assert not holds({"field": "amount", "op": "gt", "value": "lots"})
    assert not holds({"field": "amount", "op": "in", "value": ["x"]})
    assert not holds({"field": "amount", "op": "gt", "value": "1"}, {**PLACED, "amount": "garbage"})


def test_validate_reports_every_problem():
    placed = events.get("orders.placed")
    bad = {"all": [
        {"field": "nope", "op": "eq", "value": 1},
        {"field": "urgent", "op": "gt", "value": 1},
        {"field": "amount", "op": "gt", "value": "lots"},
        {"field": "amount", "op": "gt"},
        {"any": "x"},
        "junk",
    ]}

    with pytest.raises(conditions.ConditionError) as raised:
        conditions.validate(bad, placed)

    assert len(raised.value.errors) == 6
    assert "has no field 'nope'" in raised.value.errors[0]


def test_a_valid_condition_passes():
    conditions.validate({"all": [{"field": "customer", "op": "is_empty"},
                                 {"field": "amount", "op": "in", "value": "1,2"}]}, events.get("orders.placed"))
    conditions.validate({}, events.get("orders.placed"))


def test_the_schema_lists_the_fields_and_their_operators():
    schema = conditions.schema(events.get("orders.shipped"))

    assert schema["fields"][1] == {"name": "carrier", "type": "str", "label": "carrier", "required": True,
                                   "choices": ["ups", "dhl"]}
    assert "gte" not in schema["operators"]["str"] and "gte" in schema["operators"]["decimal"]
