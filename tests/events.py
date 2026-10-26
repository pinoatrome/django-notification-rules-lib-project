"""The tests' event types, discovered as an app's `events.py`."""

from django.utils.translation import gettext_lazy as _

from django_notification_rules.events import Field, event


@event(
    "orders.placed",
    fields={
        "number": Field("str", _("Order number")),
        "amount": Field("decimal", _("Amount")),
        "customer": Field("str", _("Customer"), required=False),
        "urgent": Field("bool", _("Urgent"), required=False),
        "due": Field("date", _("Due"), required=False),
    },
    templates={"*": {"subject": _("Order placed"), "body": "Order {{ number }}: {{ amount }}", "link": "/orders/{{ number }}"}},
)
def order_placed():
    """A customer placed an order."""
    return {"number": "A-1", "amount": "12.50", "customer": "ann"}


@event("orders.shipped", fields={"number": Field("str"), "carrier": Field("str", choices=("ups", "dhl"))})
def order_shipped():
    """An order left the warehouse."""
    return None
