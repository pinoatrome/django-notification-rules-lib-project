"""A rule's condition on an event's payload, stored as JSON:

    {"all": [{"field": "amount", "op": "gte", "value": "100"},
             {"any": [{"field": "dean", "op": "startswith", "value": "EU49"},
                      {"field": "urgent", "op": "eq", "value": true}]}]}

`all` holds when each of its items does, `any` when one does; an item is a test `{field, op, value}` or another
group. An empty condition (`{}`) holds for every event. The operators a field takes follow its type (`OPERATORS`);
`value` is written as the payload stores it (a decimal as a string, a date as ISO 8601), a list for `in` and
`not_in` (or a comma-separated string).
"""

from decimal import InvalidOperation

from django.utils.translation import gettext_lazy as _

from .events import EventType

COMMON = {
    "eq": _("is"),
    "ne": _("is not"),
    "in": _("is one of"),
    "not_in": _("is none of"),
    "is_empty": _("is empty"),
    "is_not_empty": _("is not empty"),
}
ORDERED = {"lt": _("is less than"), "lte": _("is at most"), "gt": _("is more than"), "gte": _("is at least")}
TEXT = {
    "contains": _("contains"),
    "not_contains": _("doesn't contain"),
    "startswith": _("starts with"),
    "endswith": _("ends with"),
}
OPERATORS = {
    "str": {**COMMON, **TEXT},
    "int": {**COMMON, **ORDERED},
    "decimal": {**COMMON, **ORDERED},
    "date": {**COMMON, **ORDERED},
    "datetime": {**COMMON, **ORDERED},
    "bool": {key: COMMON[key] for key in ("eq", "ne", "is_empty", "is_not_empty")},
}
UNARY = ("is_empty", "is_not_empty")
LISTS = ("in", "not_in")


class ConditionError(ValueError):
    """A condition that can't be evaluated against its event type: each problem in `errors`."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _group(node) -> tuple[str, list] | None:
    if isinstance(node, dict) and len(node) == 1 and next(iter(node)) in ("all", "any"):
        key = next(iter(node))
        return key, node[key]
    return None


def _values(spec, raw) -> list:
    items = raw if isinstance(raw, list) else [part.strip() for part in str(raw or "").split(",") if part.strip()]
    return [spec.parse(item) for item in items]


def validate(condition, event_type: EventType) -> None:
    """Raise `ConditionError` with every problem of `condition` for `event_type`'s fields."""
    errors: list[str] = []

    def visit(node, where: str):
        group = _group(node)
        if group is not None:
            key, items = group
            if not isinstance(items, list):
                errors.append(f"{where}: {key} takes a list")
                return
            for index, item in enumerate(items):
                visit(item, f"{where}.{key}[{index}]")
            return
        if not isinstance(node, dict) or "field" not in node or "op" not in node:
            errors.append(f"{where}: expected {{field, op, value}}, or a group all/any")
            return
        spec = event_type.fields.get(node["field"])
        if spec is None:
            errors.append(f"{where}: {event_type.code} has no field {node['field']!r}")
            return
        if node["op"] not in OPERATORS[spec.type]:
            errors.append(f"{where}: {node['field']} ({spec.type}) takes no operator {node['op']!r}")
            return
        if node["op"] in UNARY:
            return
        try:
            if node["op"] in LISTS:
                _values(spec, node.get("value"))
            elif spec.parse(node.get("value")) is None:
                errors.append(f"{where}: {node['field']} {node['op']} needs a value")
        except (ValueError, InvalidOperation):
            errors.append(f"{where}: {node.get('value')!r} isn't a {spec.type}")

    if condition:
        visit(condition, "condition")
    if errors:
        raise ConditionError(errors)


def matches(condition, event_type: EventType, payload: dict) -> bool:
    """Whether `payload` (as stored) meets `condition`. A test on a field that's missing, or of the wrong type,
    doesn't hold (`is_empty` aside)."""
    if not condition:
        return True
    parsed = event_type.parse(payload)

    def holds(node) -> bool:
        group = _group(node)
        if group is not None:
            key, items = group
            results = (holds(item) for item in items)
            return all(results) if key == "all" else any(results)
        spec = event_type.fields.get(node.get("field"))
        if spec is None:
            return False
        actual, op = parsed.get(node["field"]), node["op"]
        if op in UNARY:
            empty = actual is None or actual == ""
            return empty if op == "is_empty" else not empty
        try:
            if op in LISTS:
                found = actual in _values(spec, node.get("value"))
                return found if op == "in" else not found
            expected = spec.parse(node.get("value"))
        except (ValueError, InvalidOperation):
            return False
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if actual is None or expected is None:
            return False
        try:
            return {
                "lt": lambda: actual < expected,
                "lte": lambda: actual <= expected,
                "gt": lambda: actual > expected,
                "gte": lambda: actual >= expected,
                "contains": lambda: str(expected).lower() in str(actual).lower(),
                "not_contains": lambda: str(expected).lower() not in str(actual).lower(),
                "startswith": lambda: str(actual).lower().startswith(str(expected).lower()),
                "endswith": lambda: str(actual).lower().endswith(str(expected).lower()),
            }[op]()
        except (TypeError, KeyError):
            return False

    return holds(condition)


def schema(event_type: EventType) -> dict:
    """The fields of `event_type` and the operators each takes, for a condition builder (the admin's widget, the
    API's catalogue)."""
    return {
        "fields": [
            {
                "name": name,
                "type": spec.type,
                "label": str(spec.label or name),
                "required": spec.required,
                "choices": list(spec.choices),
            }
            for name, spec in event_type.fields.items()
        ],
        "operators": {kind: {op: str(label) for op, label in ops.items()} for kind, ops in OPERATORS.items()},
        "unary": list(UNARY),
        "lists": list(LISTS),
    }
