"""The event types the code declares, and `emit()`.

An app declares its event types in its `events.py` (discovered as the admin discovers `admin.py`):

    @event("payments.request_received", description=_("Someone asked a customer for money"),
           fields={"dean": Field("str", _("Account")), "amount": Field("decimal", _("Amount"), required=False)},
           templates={"*": {"subject": _("Payment request"), "body": _("You are asked for {{ amount }}.")}})
    def request_received():
        "The payload a preview and a test send use."
        return {"dean": "EU4900000000000001", "amount": "25.00"}

The fields describe the payload: what a rule's condition can test and what its templates can show. `templates` are
the texts a rule uses when it gives none of its own (by channel, `*` for any), in the code's language, translated
with gettext. The decorated function gives a sample payload, for the admin's preview and test send.

`emit("payments.request_received", dean=..., amount=..., actor=user)` checks the payload against the fields and,
once the transaction commits, records the `Event` and has its rules act on it (`conf.runner()`). An existing signal
can feed an event type instead: `connect_signal(signal, code, mapper)`.

The registry holds what the code declares, the same in every process: it isn't shared state.
"""

import datetime
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.module_loading import autodiscover_modules

from . import conf

logger = logging.getLogger(__name__)

FIELD_TYPES = ("str", "int", "decimal", "bool", "date", "datetime")


class UnknownEvent(LookupError):
    """No event type has this code."""


class PayloadError(ValueError):
    """A payload that doesn't match its event type's fields."""


@dataclass(frozen=True)
class Field:
    """A payload field: its type (one of `FIELD_TYPES`), its label for the admin, whether it may be missing (or
    None), and its choices when it has a fixed set of values."""

    type: str = "str"
    label: str = ""
    required: bool = True
    choices: tuple = ()

    def __post_init__(self):
        if self.type not in FIELD_TYPES:
            raise ValueError(f"Unknown field type {self.type!r}: one of {', '.join(FIELD_TYPES)}")

    def dump(self, value):
        """`value` as the payload stores it (JSON): a decimal as a string, a date as ISO 8601."""
        if value is None:
            return None
        try:
            if self.type == "str":
                return str(value)
            if self.type == "int":
                if isinstance(value, bool):
                    raise TypeError
                return int(value)
            if self.type == "decimal":
                return str(Decimal(str(value)))
            if self.type == "bool":
                if not isinstance(value, bool):
                    raise TypeError
                return value
            return self.parse(value).isoformat()  # a date, a datetime
        except (TypeError, ValueError, InvalidOperation, AttributeError) as exc:
            raise PayloadError(f"{value!r} isn't a {self.type}") from exc

    def parse(self, raw):
        """A stored (or typed) value back as Python: what conditions compare and templates show."""
        if raw is None or raw == "":
            return None
        if self.type == "int":
            return int(raw)
        if self.type == "decimal":
            return Decimal(str(raw))
        if self.type == "bool":
            return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
        if self.type == "date":
            if isinstance(raw, datetime.datetime):
                return raw.date()
            return raw if isinstance(raw, datetime.date) else datetime.date.fromisoformat(str(raw))
        if self.type == "datetime":
            if isinstance(raw, datetime.datetime):
                return raw
            return datetime.datetime.fromisoformat(str(raw))
        return str(raw)


@dataclass
class EventType:
    code: str
    fields: dict[str, Field] = field(default_factory=dict)
    description: str = ""
    sample: Callable[[], dict] | None = None
    templates: dict[str, dict[str, str]] = field(default_factory=dict)
    module: str = ""

    def dump(self, payload: dict) -> dict:
        """`payload` checked against the fields and made storable; raises `PayloadError`."""
        unknown = sorted(set(payload) - set(self.fields))
        if unknown:
            raise PayloadError(f"{self.code}: unknown payload fields {', '.join(unknown)}")
        data = {}
        for name, spec in self.fields.items():
            value = payload.get(name)
            if value is None and spec.required:
                raise PayloadError(f"{self.code}: the payload needs {name}")
            try:
                data[name] = spec.dump(value)
            except PayloadError as exc:
                raise PayloadError(f"{self.code}.{name}: {exc}") from exc
        return data

    def parse(self, data: dict) -> dict:
        """A stored payload with its values as Python (decimals, dates); fields it lacks are None."""
        parsed = {}
        for name, spec in self.fields.items():
            try:
                parsed[name] = spec.parse(data.get(name))
            except (ValueError, InvalidOperation):
                parsed[name] = data.get(name)
        return parsed

    def sample_payload(self) -> dict:
        """The sample the code gives, else (none, or a function that returns none) a made-up one: a value of each
        field's type."""
        given = self.sample() if self.sample is not None else None
        if given:
            return self.dump(given)
        made_up = {
            "str": "…",
            "int": 1,
            "decimal": "1.00",
            "bool": True,
            "date": "2026-01-01",
            "datetime": "2026-01-01T12:00:00+00:00",
        }
        return {name: (spec.choices[0] if spec.choices else made_up[spec.type]) for name, spec in self.fields.items()}

    def template(self, channel: str) -> dict[str, str]:
        """The code's default texts for `channel` (`*`: any channel)."""
        return self.templates.get(channel) or self.templates.get("*") or {}


REGISTRY: dict[str, EventType] = {}


def declare(
    code: str,
    *,
    fields: dict[str, Field] | None = None,
    description: str = "",
    sample=None,
    templates: dict | None = None,
) -> EventType:
    """Register an event type (what `@event` does, without a sample function)."""
    reserved = sorted(set(fields or {}) & {"event", "recipient"})
    if reserved:
        raise ValueError(f"{code}: {', '.join(reserved)} is a name the templates keep for themselves")
    module = getattr(sample, "__module__", "") if sample else ""
    REGISTRY[code] = EventType(code, dict(fields or {}), description, sample, dict(templates or {}), module)
    return REGISTRY[code]


def event(code: str, *, fields: dict[str, Field] | None = None, description: str = "", templates: dict | None = None):
    """Declare an event type; the decorated function gives its sample payload. The description defaults to the
    function's docstring's first paragraph."""

    def register(sample):
        text = description or (inspect.getdoc(sample) or "").split("\n\n")[0].replace("\n", " ")
        declare(code, fields=fields, description=text, sample=sample, templates=templates)
        return sample

    return register


def discover():
    """Import each installed app's `events` module (the `@event` declarations)."""
    autodiscover_modules("events")


def get(code: str) -> EventType:
    try:
        return REGISTRY[code]
    except KeyError:
        raise UnknownEvent(f"No event type {code!r}") from None


def choices() -> list[tuple[str, str]]:
    """The event types for a select: (code, "code — description")."""
    return [
        (code, f"{code} — {kind.description}" if kind.description else code) for code, kind in sorted(REGISTRY.items())
    ]


def emit(code: str, *, actor=None, **payload) -> None:
    """Record an event of type `code` once the transaction commits, and have its rules act on it. Raises
    `UnknownEvent` and `PayloadError` right away, for the code to see; what happens after the commit is logged."""
    data = get(code).dump(payload)
    actor_id = getattr(actor, "pk", None)

    def record():
        from .models import Event

        recorded = Event.objects.create(code=code, payload=data, actor_id=actor_id)
        conf.runner()(recorded.pk)

    transaction.on_commit(record, robust=True)


def connect_signal(signal, code: str, mapper: Callable[..., dict | None], dispatch_uid: str | None = None):
    """Emit `code` each time `signal` is sent: `mapper(sender, **kwargs)` gives the payload (an `actor` key is the
    actor), or None for a sending that isn't one. Returns the receiver."""

    def receiver(sender, **kwargs):
        payload = mapper(sender, **kwargs)
        if payload is None:
            return
        payload = dict(payload)
        actor = payload.pop("actor", None)
        emit(code, actor=actor, **payload)

    signal.connect(receiver, weak=False, dispatch_uid=dispatch_uid or f"django_notification_rules.{code}")
    return receiver
